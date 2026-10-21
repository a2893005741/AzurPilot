"""只读访问实例已保存的错误现场，不连接设备或启动游戏。"""
import base64
import re

from module.api.protocol import ApiError

RECORD_ID = re.compile(r'[0-9]{13}\Z')
IMAGE_NAME = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}-[0-9]{6}\.png\Z')
LOG_LIMIT = 256 * 1024
FILE_LIMIT = 8 * 1024 * 1024


def child(parent, name):
    """拒绝符号链接和目录联接把读取指向其他位置。"""
    path = parent / name
    if path.resolve() != parent.resolve() / name:
        raise ApiError('INVALID_PARAMS', '错误现场路径无效')
    return path


class ErrorService:
    def __init__(self, configs):
        self.configs = configs

    def folder(self, instance):
        name = self.configs.path(instance).stem
        return child(child(child(self.configs.root, 'log'), 'error'), name)

    def record(self, instance, record):
        if not RECORD_ID.fullmatch(record):
            raise ApiError('INVALID_PARAMS', '故障记录编号无效')
        path = child(self.folder(instance), record)
        if not path.is_dir():
            raise ApiError('NOT_FOUND', '故障记录不存在或已被清理，请刷新列表')
        return path

    @staticmethod
    def images(folder):
        return sorted(file.name for file in folder.iterdir()
                      if IMAGE_NAME.fullmatch(file.name) and child(folder, file.name).is_file())

    def list(self, instance, offset=0, limit=30):
        folder = self.folder(instance)
        values, _ = self.configs.read(instance)
        records = sorted((file.name for file in folder.iterdir()
                          if RECORD_ID.fullmatch(file.name) and child(folder, file.name).is_dir()),
                         reverse=True) if folder.is_dir() else []
        entries = []
        for record in records[offset:offset + limit]:
            path = child(folder, record)
            try:
                entries.append(dict(id=record, timestamp=int(record), screenshots=len(self.images(path)),
                                    has_log=child(path, 'log.txt').is_file()))
            except FileNotFoundError:
                # 调度器可能在列举期间按保留天数清理现场；下一次刷新重新对齐列表。
                continue
        return dict(instance=instance, entries=entries, total=len(records),
                    enabled=values.get('Alas', {}).get('Error', {}).get('SaveError', False))

    def detail(self, instance, record):
        path = self.record(instance, record)
        try:
            images = self.images(path)
        except FileNotFoundError:
            # 保留策略可能在路径核验之后删除整条现场。
            raise ApiError('NOT_FOUND', '故障记录不存在或已被清理，请刷新列表') from None
        log = child(path, 'log.txt')
        try:
            with log.open('rb') as stream:
                size = stream.seek(0, 2)
                start = max(0, size - LOG_LIMIT)
                stream.seek(start)
                content = stream.read(LOG_LIMIT).decode('utf-8', errors='replace')
        except FileNotFoundError:
            # 未初始化日志或保存日志失败的现场仍可查看已有截图。
            return dict(instance=instance, id=record, images=images, log=None, truncated=False)
        return dict(instance=instance, id=record, images=images, log=content, truncated=start > 0)

    def file(self, instance, record, name):
        if name != 'log.txt' and not IMAGE_NAME.fullmatch(name):
            raise ApiError('INVALID_PARAMS', '只能读取现场日志和截图')
        path = child(self.record(instance, record), name)
        try:
            with path.open('rb') as stream:
                data = stream.read(FILE_LIMIT + 1)
        except FileNotFoundError:
            raise ApiError('NOT_FOUND', '现场文件不存在或已被清理，请刷新列表') from None
        if len(data) > FILE_LIMIT:
            raise ApiError('INVALID_PARAMS', '单个现场文件超过 8 MiB，无法通过网页传输')
        return dict(filename=name, content=base64.b64encode(data).decode('ascii'),
                    media_type='text/plain' if name == 'log.txt' else 'image/png')
