import os
import gc
import threading
import time
from module.exception import RequestHumanTakeover
from module.logger import logger
from module.config.config import AzurLaneConfig

def handle_ocr_error(e):
    logger.critical(f"Failed to load OCR dependencies: {e}")
    logger.critical(
        "无法加载 OCR 依赖，请安装微软 C++ 运行库 https://aka.ms/vs/17/release/vc_redist.x64.exe"
    )
    logger.critical("也有可能是 GPU 不支持加速引起，请尝试关闭 GPU 加速")
    logger.critical("如果上述方法都无法解决，请加群获取支持")
    raise RequestHumanTakeover


OCRVersion = None
ParseParams = None
TextRecInput = None
TextRecognizer = None
LoadImage = None
DEFAULT_CFG_PATH = None


def ensure_ocr_dependencies():
    global OCRVersion, ParseParams, TextRecInput, TextRecognizer, LoadImage, DEFAULT_CFG_PATH
    if TextRecognizer is not None:
        return

    try:
        from rapidocr import OCRVersion as _OCRVersion
        from rapidocr.ch_ppocr_rec import TextRecInput as _TextRecInput
        from rapidocr.ch_ppocr_rec import TextRecognizer as _TextRecognizer
        from rapidocr.main import DEFAULT_CFG_PATH as _DEFAULT_CFG_PATH
        from rapidocr.utils.load_image import LoadImage as _LoadImage
        from rapidocr.utils.parse_parameters import ParseParams as _ParseParams
    except Exception as e:
        handle_ocr_error(e)
    OCRVersion = _OCRVersion
    ParseParams = _ParseParams
    TextRecInput = _TextRecInput
    TextRecognizer = _TextRecognizer
    LoadImage = _LoadImage
    DEFAULT_CFG_PATH = _DEFAULT_CFG_PATH


class RecOnlyOCR:
    def __init__(self, params):
        ensure_ocr_dependencies()
        cfg = ParseParams.load(DEFAULT_CFG_PATH)
        cfg = ParseParams.update_batch(cfg, params)
        cfg.Rec.engine_cfg = cfg.EngineConfig[cfg.Rec.engine_type.value]
        cfg.Rec.font_path = cfg.Global.font_path

        self.load_img = LoadImage()
        self.text_rec = TextRecognizer(cfg.Rec)

    def __call__(self, img):
        img = self.load_img(img)
        return self.text_rec(TextRecInput(img=img))


config_name = None
config = None
USE_GPU = False
OCR_IDLE_TIMEOUT = float(os.environ.get("ALAS_OCR_IDLE_TIMEOUT", "60"))
OCR_IDLE_TIMEOUTS = {
    "cn": float(os.environ.get("ALAS_OCR_CN_IDLE_TIMEOUT", "20")),
}


def get_config():
    global config_name, config
    current_config_name = os.environ.get("ALAS_CONFIG_NAME") or "alas"
    if config is None or config_name != current_config_name:
        config_name = current_config_name
        config = AzurLaneConfig(config_name)
    return config


def refresh_ocr_device():
    global USE_GPU
    USE_GPU = get_config().ocr_device == 'gpu'
    return USE_GPU

class CnModel:
    def __init__(self):
        ensure_ocr_dependencies()
        self.params = {
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_path": "bin/ocr_models/zh-CN/alocr-zh-cn-v3.dtk.onnx",
            "Rec.rec_keys_path": "bin/ocr_models/zh-CN/cn.txt",
            "EngineConfig.onnxruntime.use_dml": USE_GPU
        }
        self.model = RecOnlyOCR(params=self.params)


class EnModel:
    def __init__(self):
        ensure_ocr_dependencies()
        self.params = {
            "Rec.ocr_version": OCRVersion.PPOCRV4,
            "Rec.model_path": "bin/ocr_models/en-US/alocr-en-us-v2.6.nvc.onnx",
            "Rec.rec_keys_path": "bin/ocr_models/en-US/en.txt",
            "EngineConfig.onnxruntime.use_dml": USE_GPU
        }
        self.model = RecOnlyOCR(params=self.params)


class JpModel:
    def __init__(self):
        ensure_ocr_dependencies()
        self.params = {
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_path": "bin/ocr_models/JP/JP.onnx",
            "Rec.rec_keys_path": "bin/ocr_models/JP/ppocrv5_dict.txt",
            "EngineConfig.onnxruntime.use_dml": USE_GPU
        }
        self.model = RecOnlyOCR(params=self.params)


class TwModel:
    def __init__(self):
        ensure_ocr_dependencies()
        self.params = {
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_path": "bin/ocr_models/TW/TW.onnx",
            "Rec.rec_keys_path": "bin/ocr_models/TW/ppocrv5_dict.txt",
            "EngineConfig.onnxruntime.use_dml": USE_GPU
        }
        self.model = RecOnlyOCR(params=self.params)


class OcrModelManager:
    MODEL_CLASSES = {
        "cn": CnModel,
        "en": EnModel,
        "jp": JpModel,
        "tw": TwModel,
    }
    NAME_ALIASES = {
        "zhcn": "cn",
    }

    def __init__(self, idle_timeout=OCR_IDLE_TIMEOUT):
        self.idle_timeout = max(0, idle_timeout)
        self._models = {}
        self._last_used = {}
        self._in_use = {}
        self._timers = {}
        self._lock = threading.RLock()

    def _normalize_name(self, name):
        return self.NAME_ALIASES.get(name, name)

    def _idle_timeout(self, name):
        return max(0, OCR_IDLE_TIMEOUTS.get(name, self.idle_timeout))

    def _load_locked(self, name):
        if name in self._models:
            return self._models[name]

        refresh_ocr_device()
        logger.info(f"Loading OCR model: {name}, USE_GPU={USE_GPU}")
        try:
            model = self.MODEL_CLASSES.get(name, EnModel)().model
        except Exception as e:
            handle_ocr_error(e)

        self._models[name] = model
        self._last_used[name] = time.monotonic()
        self._in_use.setdefault(name, 0)
        return model

    def ensure_loaded(self, name):
        name = self._normalize_name(name)
        with self._lock:
            self._load_locked(name)
            self._schedule_unload_locked(name)

    def acquire(self, name):
        name = self._normalize_name(name)
        with self._lock:
            model = self._load_locked(name)
            self._in_use[name] = self._in_use.get(name, 0) + 1
            self._last_used[name] = time.monotonic()
            return name, model

    def release(self, name):
        name = self._normalize_name(name)
        with self._lock:
            self._in_use[name] = max(0, self._in_use.get(name, 0) - 1)
            self._last_used[name] = time.monotonic()
            self._schedule_unload_locked(name)

    def request_unload(self, names=None, delay=None):
        with self._lock:
            if names is None:
                names = list(self._models.keys())
            for name in names:
                name = self._normalize_name(name)
                if name in self._models:
                    if delay is not None:
                        idle_timeout = self._idle_timeout(name)
                        self._last_used[name] = (
                            time.monotonic()
                            - max(0, idle_timeout - max(0, delay))
                        )
                    self._schedule_unload_locked(name, delay=delay)

    def unload_all(self, force=False):
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
            if force:
                self._models.clear()
                self._last_used.clear()
                self._in_use.clear()
                gc.collect()
            else:
                self.request_unload(delay=0)

    def _schedule_unload_locked(self, name, delay=None):
        if name not in self._models:
            return

        timer = self._timers.pop(name, None)
        if timer is not None:
            timer.cancel()

        delay = self._idle_timeout(name) if delay is None else max(0, delay)
        timer = threading.Timer(delay, self._unload_if_idle, args=(name,))
        timer.daemon = True
        self._timers[name] = timer
        timer.start()

    def _unload_if_idle(self, name):
        with self._lock:
            self._timers.pop(name, None)
            if name not in self._models:
                return

            if self._in_use.get(name, 0):
                self._schedule_unload_locked(name)
                return

            idle_timeout = self._idle_timeout(name)
            idle_time = time.monotonic() - self._last_used.get(name, 0)
            if idle_time < idle_timeout:
                self._schedule_unload_locked(name, delay=idle_timeout - idle_time)
                return

            logger.info(f"Unloading idle OCR model: {name}")
            del self._models[name]
            self._last_used.pop(name, None)
            self._in_use.pop(name, None)
            gc.collect()


OCR_MODEL_MANAGER = OcrModelManager()

def reset_ocr_model():
    refresh_ocr_device()
    logger.info(f"Resetting OCR models, USE_GPU={USE_GPU}")
    OCR_MODEL_MANAGER.unload_all(force=True)


def release_ocr_models(names=None, delay=None):
    OCR_MODEL_MANAGER.request_unload(names=names, delay=delay)


class AlOcr:
    def __init__(self, **kwargs):
        self.model = None
        self.name = kwargs.get("name", "en")
        self.params = {}
        self._model_loaded = False
        logger.info(
            f"Created AlOcr instance: name='{self.name}', kwargs={kwargs}, PID={os.getpid()}"
        )

    def init(self):
        OCR_MODEL_MANAGER.ensure_loaded(self.name)
        self._model_loaded = True

    def _ensure_loaded(self):
        self.init()

    def _acquire_model(self):
        name, model = OCR_MODEL_MANAGER.acquire(self.name)
        self._model_loaded = True
        return name, model

    def _save_debug_image(self, img, result):
        return

    def ocr(self, img_fp):
        logger.debug(f"[VERBOSE] AlOcr.ocr: Ensure loaded...")
        model_name, model = self._acquire_model()

        try:
            res = model(img_fp)
            txt = ""
            if hasattr(res, "txts") and res.txts:
                txt = res.txts[0]

            self._save_debug_image(img_fp, txt)
            return txt
        except Exception as e:
            logger.error(f"AlOcr.ocr exception: {e}")
            raise
        finally:
            OCR_MODEL_MANAGER.release(model_name)

    def ocr_for_single_line(self, img_fp):
        return self.ocr(img_fp)

    def ocr_for_single_lines(self, img_list):
        model_name, model = self._acquire_model()
        results = []
        try:
            for i, img in enumerate(img_list):
                try:
                    res = model(img)
                    txt = ""
                    if hasattr(res, "txts") and res.txts:
                        txt = res.txts[0]

                    results.append(txt)
                    self._save_debug_image(img, txt)
                except Exception as e:
                    logger.error(f"AlOcr.ocr_for_single_lines exception on image {i}: {e}")
                    raise
        finally:
            OCR_MODEL_MANAGER.release(model_name)
        return results

    def set_cand_alphabet(self, cand_alphabet):
        pass

    def atomic_ocr(self, img_fp, cand_alphabet=None):
        res = self.ocr(img_fp)
        if cand_alphabet:
            res = "".join([c for c in res if c in cand_alphabet])
        return res

    def atomic_ocr_for_single_line(self, img_fp, cand_alphabet=None):
        res = self.ocr_for_single_line(img_fp)
        if cand_alphabet:
            res = "".join([c for c in res if c in cand_alphabet])
        return res

    def atomic_ocr_for_single_lines(self, img_list, cand_alphabet=None):
        results = self.ocr_for_single_lines(img_list)
        if cand_alphabet:
            results = [
                "".join([c for c in res if c in cand_alphabet]) for res in results
            ]
        return results
