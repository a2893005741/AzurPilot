"""作战委托 Plus 任务。

作战委托占用指定关卡期间不能进行普通出击，因此本任务只处理关卡详情中的
作战委托面板，不调用 ``CampaignBase.run`` 或普通战斗流程。
"""

import re
from datetime import timedelta

from module.base.button import Button
from module.campaign.assets import (
    DELEGATION_BATTLE_MAX,
    DELEGATION_BATTLE_MINUS,
    DELEGATION_BATTLE_PLUS,
    DELEGATION_BOOK_MAX,
    DELEGATION_BOOK_MINUS,
    DELEGATION_BOOK_PLUS,
    DELEGATION_DETAIL_CLAIM,
    DELEGATION_HANDOVER_START,
    DELEGATION_SHIP_SKIP,
    DELEGATION_TOTAL_CONFIRM,
    DELEGATION_TOTAL_LEAVE,
    OPERATION_HANDOVER_ENTRY,
    OPERATION_HANDOVER_PANEL_CLOSE,
)
from module.campaign.run import CampaignRun
from module.config.time_source import now as current_time
from module.logger import logger
from module.ocr.ocr import Ocr


DELEGATION_DETAIL_CLOSE = OPERATION_HANDOVER_PANEL_CLOSE

OCR_DELEGATION_BATTLE_COUNT = Button(
    area=(320, 244, 414, 283), color=(45, 45, 52), button=(),
    name='OCR_DELEGATION_BATTLE_COUNT')
OCR_DELEGATION_BOOK_COUNT = Button(
    area=(808, 244, 902, 283), color=(45, 45, 52), button=(),
    name='OCR_DELEGATION_BOOK_COUNT')
OCR_DELEGATION_REQUIRED_TIME = Button(
    area=(520, 321, 611, 348), color=(45, 45, 52), button=(),
    name='OCR_DELEGATION_REQUIRED_TIME')
OCR_DELEGATION_REMAINING_TIME = Button(
    area=(520, 362, 611, 389), color=(45, 145, 66), button=(),
    name='OCR_DELEGATION_REMAINING_TIME')
# 面板右上角的委托书图标计数，用于防止库存不足时部分启动。
OCR_DELEGATION_BOOK_STOCK = Button(
    area=(1170, 12, 1250, 62), color=(120, 129, 149), button=(),
    name='OCR_DELEGATION_BOOK_STOCK')

_OCR_COUNT = Ocr(OCR_DELEGATION_BATTLE_COUNT, alphabet='0123456789', name='OCR_DELEGATION_BATTLE_COUNT')
_OCR_BOOK_COUNT = Ocr(OCR_DELEGATION_BOOK_COUNT, alphabet='0123456789', name='OCR_DELEGATION_BOOK_COUNT')
_OCR_REQUIRED_TIME = Ocr(
    OCR_DELEGATION_REQUIRED_TIME, alphabet='0123456789:', name='OCR_DELEGATION_REQUIRED_TIME')
_OCR_REMAINING_TIME = Ocr(
    OCR_DELEGATION_REMAINING_TIME, alphabet='0123456789:', name='OCR_DELEGATION_REMAINING_TIME')
_OCR_BOOK_STOCK = Ocr(OCR_DELEGATION_BOOK_STOCK, alphabet='0123456789', name='OCR_DELEGATION_BOOK_STOCK')

_HANDOVER_MAX_COUNT = 15
_HANDOVER_ADJUST_LIMIT = 5


def _parse_count(value):
    match = re.search(r'\d+', str(value or ''))
    return int(match.group()) if match else None


def _parse_duration(value):
    match = re.search(r'(\d{1,2}):?(\d{2}):?(\d{2})', str(value or ''))
    if not match:
        return None
    hours, minutes, seconds = (int(item) for item in match.groups())
    return timedelta(hours=hours, minutes=minutes, seconds=seconds)


class OperationHandover(CampaignRun):
    """只处理作战委托面板的独立任务。"""

    def run(self):
        """进入配置关卡，处理当前一批作战委托后返回。"""
        name, folder = self.handle_stage_name(
            self.config.Campaign_Name,
            self.config.Campaign_Event,
            mode=self.config.Campaign_Mode,
        )
        self.config.override(Campaign_Name=name, Campaign_Event=folder,
                             Campaign_Mode=self.config.Campaign_Mode)
        self.load_campaign(name, folder=folder)
        self.campaign.ensure_campaign_ui(name=self.stage, mode=self.config.Campaign_Mode)

        for _ in self.loop(timeout=30):
            if self.appear(OPERATION_HANDOVER_ENTRY, offset=(20, 20)):
                self.device.click(OPERATION_HANDOVER_ENTRY)
                break
            if self.appear(self.campaign.ENTRANCE, offset=(20, 20)):
                self.device.click(self.campaign.ENTRANCE)
                continue
        else:
            logger.warning('[作战委托] 未找到关卡详情入口，延后任务')
            self.config.task_delay(success=False)
            return

        self._handover_finished = False
        for _ in self.loop(timeout=90):
            if self.handle_handover_panel():
                if self._handover_finished:
                    break
                continue
            logger.warning('[作战委托] 无法确认面板状态，保守延后')
            self.config.task_delay(minute=30)
            break

    def _read_count(self, ocr):
        try:
            return _parse_count(ocr.ocr(self.device.image))
        except Exception:
            return None

    def _read_handover_duration(self):
        try:
            return _parse_duration(_OCR_REQUIRED_TIME.ocr(self.device.image))
        except Exception:
            return None

    def _read_handover_remaining(self):
        try:
            return _parse_duration(_OCR_REMAINING_TIME.ocr(self.device.image))
        except Exception:
            return None

    def _read_available_books(self):
        try:
            return self._read_count(_OCR_BOOK_STOCK)
        except Exception:
            return None

    def _set_handover_value(self, ocr, target, plus, minus, maximum, label, max_button):
        """通过 OCR 设置单项数量，并限制连续点击次数避免误触保护。"""
        max_clicked = False
        click_count = 0
        while 1:
            current = self._read_count(ocr)
            if current is None:
                logger.warning(f'[作战委托] 无法识别{label}，取消启动')
                return False
            if current == target:
                return True

            # 目标是合法上限时使用截图裁切的 MAX 模板，避免连续点击十余次。
            if target == maximum and current < target and not max_clicked:
                self.device.click(max_button)
                self.device.screenshot()
                max_clicked = True
                continue
            if max_clicked or click_count >= _HANDOVER_ADJUST_LIMIT:
                logger.warning(f'[作战委托] {label}调整未完成，保守延后')
                return False

            button = plus if current < target else minus
            self.device.click(button)
            self.device.screenshot()
            click_count += 1

    def _set_handover_amount(self, battle_count, book_count):
        """通过 OCR 和加减/MAX 按钮把两项数量设置到固定目标。"""
        if not self._set_handover_value(
                _OCR_COUNT, battle_count, DELEGATION_BATTLE_PLUS, DELEGATION_BATTLE_MINUS,
                _HANDOVER_MAX_COUNT, '作战次数', DELEGATION_BATTLE_MAX):
            return False
        return self._set_handover_value(
            _OCR_BOOK_COUNT, book_count, DELEGATION_BOOK_PLUS, DELEGATION_BOOK_MINUS,
            _HANDOVER_MAX_COUNT, '全权委托书数量', DELEGATION_BOOK_MAX)

    def _delay_until(self, duration):
        if duration is None:
            logger.warning('[作战委托] 无法识别剩余时间，延后 30 分钟')
            self.config.task_delay(minute=30)
        else:
            self.config.task_delay(target=current_time() + duration)

    def _handle_reward_flow(self):
        if self.handle_popup_confirm(name='DELEGATION_REWARD_OVERFLOW'):
            return True
        if self.appear(DELEGATION_SHIP_SKIP, offset=(20, 20), interval=1):
            self.device.click(DELEGATION_SHIP_SKIP)
            return True
        if self.appear(DELEGATION_TOTAL_CONFIRM, offset=(20, 20), interval=1):
            self.device.click(DELEGATION_TOTAL_CONFIRM)
            return True
        if self.appear(DELEGATION_TOTAL_LEAVE, offset=(20, 20), interval=1):
            self.device.click(DELEGATION_TOTAL_LEAVE)
            self._handover_finished = True
            self._reward_flow = False
            self.config.task_delay(success=True)
            return True
        return False

    def handle_handover_panel(self):
        """处理面板当前可确认的一步，返回是否完成了一次操作。"""
        if getattr(self, '_handover_start_pending', False):
            if self.appear(OPERATION_HANDOVER_PANEL_CLOSE, offset=(20, 20), interval=1):
                logger.info('[作战委托] 已确认作战启动，关闭详情并等待')
                remaining = self._read_handover_remaining() or self._handover_start_duration
                self.device.click(OPERATION_HANDOVER_PANEL_CLOSE)
                self._delay_until(remaining)
                self._handover_start_pending = False
                self._handover_finished = True
                return True
            return False

        if getattr(self, '_reward_flow', False):
            return self._handle_reward_flow()

        # 任务重启后若停留在奖励页，仍优先完成奖励流程，避免重新启动委托。
        if any(self.appear(button, offset=(20, 20), interval=1) for button in (
                DELEGATION_SHIP_SKIP, DELEGATION_TOTAL_CONFIRM, DELEGATION_TOTAL_LEAVE)):
            self._reward_flow = True
            # 上面的检测已经消耗了按钮 interval，等待下一帧再执行点击。
            return True

        if self.appear(DELEGATION_DETAIL_CLAIM, offset=(20, 20), interval=1):
            logger.info('[作战委托] 领取已完成的作战委托')
            self.device.click(DELEGATION_DETAIL_CLAIM)
            self._reward_flow = True
            return True

        if self.appear(DELEGATION_HANDOVER_START, offset=(20, 20), interval=1):
            battle_count = max(1, int(self.config.OperationHandover_BattleCount))
            book_count = max(0, int(self.config.OperationHandover_FullDelegationBookCount))
            stock = self._read_available_books() if book_count else 0
            if book_count and (stock is None or stock < book_count):
                logger.warning('[作战委托] 全权委托书库存不足，不启动本批次')
                self.config.task_delay(server_update=True)
                self._handover_finished = True
                return True
            if not self._set_handover_amount(battle_count, book_count):
                self.config.task_delay(minute=30)
                self._handover_finished = True
                return True

            # 数量变化会改变委托耗时，必须在刷新截图后重新 OCR 时间。
            self.device.screenshot()
            required = self._read_handover_duration()
            available = self._read_handover_remaining()
            if required is None or available is None or available < required:
                logger.warning('[作战委托] 可用时间不足或 OCR 失败，不启动本批次')
                self.config.task_delay(server_update=True)
                self._handover_finished = True
                return True

            self.device.click(DELEGATION_HANDOVER_START)
            self._handover_start_duration = required
            self._handover_start_pending = True
            return True

        if self.appear(OPERATION_HANDOVER_PANEL_CLOSE, offset=(20, 20), interval=1):
            remaining = self._read_handover_remaining()
            logger.info('[作战委托] 作战进行中，关闭详情并等待')
            self.device.click(OPERATION_HANDOVER_PANEL_CLOSE)
            self._delay_until(remaining)
            self._handover_finished = True
            return True

        logger.warning('[作战委托] 未知面板状态')
        self.config.task_delay(minute=30)
        self._handover_finished = True
        return True
