"""作战委托面板的补时与用书准备状态机，由任务截图循环驱动。"""

import math
from datetime import timedelta

from module.base.timer import Timer
from module.campaign.assets import (
    DELEGATION_BOOK_MAX, DELEGATION_BOOK_MINUS, DELEGATION_HANDOVER_START,
)
from module.handler.assets import POPUP_CONFIRM
from module.map.assets import HANDOVER_BOOK_ITEM, HANDOVER_EXCHANGE_TIME


class HandoverPreparation:
    """每次调用至多发出一次兑换或 MAX 操作，不自行启动截图循环。"""

    def _begin_handover_preparation(self):
        self._handover_preparing = 'books' if self._handover_consume_all else 'time'
        self._handover_consume_count_ready = False
        self._handover_fixed_books = self.config.OperationHandover_FullDelegationBookCount
        self._handover_use_max = self.config.OperationHandover_UseHandoverBook or self._handover_consume_all
        self._handover_auto_time = self.config.OperationHandover_AutoSupplementTime

    def _prepare_handover(self):
        phase = self._handover_preparing
        reserve = 0 if self._handover_use_max else self._handover_fixed_books

        if phase == 'time':
            required = self._read_handover_duration()
            available = self._read_handover_remaining()
            if required is None or available is None:
                return self._delay_retry('无法确认耗时或可用时间')
            need = max(0, math.ceil((required - available).total_seconds() / 3600))
            if need and not self._handover_auto_time:
                return self._delay_server_update('可用时间不足且未启用自动补充')
            if reserve or need:
                stock = self._read_available_books()
                if stock is None:
                    return self._delay_retry('无法确认委托书库存')
                if stock < reserve + need:
                    return self._delay_server_update('库存不足以同时补时和固定投入')
            self._handover_required = required
            self._handover_available = available
            self._handover_preparing = ('exchange_open' if need else
                                       'final' if self._handover_consume_count_ready else 'books')
            return True

        if phase == 'exchange_open':
            if self.appear(POPUP_CONFIRM, offset=self._popup_offset):
                stock = self._read_exchange_books()
                need = math.ceil((self._handover_required - self._handover_available).total_seconds() / 3600)
                if stock is None or stock < reserve + need:
                    self.handle_popup_cancel('HANDOVER')
                    if stock is None:
                        return self._delay_retry('无法确认兑换库存')
                    return self._delay_server_update('兑换库存不足，保留固定用书')
                self._handover_preparing = 'exchange_select'
                return True
            return self.appear_then_click(HANDOVER_EXCHANGE_TIME, interval=2)

        if phase == 'exchange_select':
            # 每次只选一本，避免把库存显示误当成已选择数量或已消费数量。
            if self.appear_then_click(HANDOVER_BOOK_ITEM, offset=(20, 20), interval=2):
                self._handover_preparing = 'exchange_confirm'
                return True
            return False

        if phase == 'exchange_confirm':
            if self.handle_popup_confirm('HANDOVER'):
                self._handover_preparing = 'exchange_verify'
                self._handover_observe_timer = Timer(5).start()
                return True
            return False

        if phase == 'exchange_verify':
            # 确认只发送一次。确认丢失或到账不明时不重复消费，交给下次任务重新读取。
            if self.appear(DELEGATION_HANDOVER_START, offset=(20, 20)):
                available = self._read_handover_remaining()
                if available is not None and available >= self._handover_available + timedelta(seconds=3590):
                    self._handover_available = available
                    if self._handover_consume_all:
                        self._handover_consume_count_ready = False
                        self._handover_preparing = 'books'
                        return True
                    self._handover_preparing = (
                        'exchange_open' if available < self._handover_required else 'books')
                    return True
            if self._handover_observe_timer.reached():
                self.handle_popup_cancel('HANDOVER')
                return self._delay_retry('补时到账未确认，不重复兑换')
            return False

        if phase == 'books':
            if not self._handover_use_max:
                if reserve:
                    stock = self._read_available_books()
                    if stock is None:
                        return self._delay_retry('无法确认固定投入库存')
                    if stock < reserve:
                        return self._delay_server_update('固定投入委托书库存不足')
                if not self._set_fixed_handover_books(reserve):
                    return self._delay_retry('固定投入数量未确认')
                self._handover_preparing = 'final'
                return True
            count = self._read_selected_books()
            stock = self._read_available_books()
            if count is None or stock is None:
                return self._delay_retry('无法确认最大投入数量或库存')
            if stock == 0 and count == 0:
                if self._handover_consume_all:
                    return self._delay_retry('没有可投入的委托书')
                self._handover_preparing = 'final'
                return True
            # 已经最大时 MAX 不改变数字；先减一本再 MAX，必须观察到真实变化。
            self._handover_max_before = count
            self._handover_preparing = 'max_reduce' if count else 'max_click'
            return True

        if phase == 'max_reduce':
            if self.appear_then_click(DELEGATION_BOOK_MINUS, offset=(20, 20), interval=2):
                self._handover_observe_timer = Timer(5).start()
                self._handover_preparing = 'max_reduce_wait'
                return True
            return False

        if phase == 'max_reduce_wait':
            count = self._read_selected_books()
            if count == self._handover_max_before - 1:
                self._handover_max_before = count
                self._handover_preparing = 'max_click'
                return True
            if self._handover_observe_timer.reached():
                return self._delay_retry('MAX 前数量调整未确认')
            return False

        if phase == 'max_click':
            if self.appear_then_click(DELEGATION_BOOK_MAX, offset=(20, 20), interval=2):
                self._handover_observe_timer = Timer(2).start()
                self._handover_max_observed = None
                self._handover_preparing = 'max_verify'
                return True
            return False

        if phase == 'max_verify':
            count = self._read_selected_books()
            if count is None:
                return self._delay_retry('无法确认 MAX 后投入量')
            if count != self._handover_max_observed:
                self._handover_max_observed = count
                self._handover_observe_timer.reset()
                return True
            if self._handover_observe_timer.reached():
                if count > self._handover_max_before:
                    self._handover_preparing = 'consume_count' if self._handover_consume_all else 'final'
                    return True
                return self._delay_retry('MAX 操作未生效')
            return False

        if phase == 'consume_count':
            count = self._read_selected_books()
            if count is None or count <= 0 or not self._input_battle_count(count):
                return self._delay_retry('清书次数输入未确认')
            self._handover_consume_count_ready = True
            self._handover_preparing = 'time'
            return True

        if phase == 'final':
            required = self._read_handover_duration()
            available = self._read_handover_remaining()
            if required is None or available is None:
                return self._delay_retry('无法确认最终耗时或可用时间')
            if required > available:
                if self._handover_auto_time:
                    self._handover_preparing = 'time'
                    return True
                return self._delay_server_update('最终耗时超过可用时间')
            if self._handover_consume_all:
                count = self._read_selected_books()
                stock = self._read_available_books()
                if count is None or stock is None or count <= 0 or count > stock:
                    return self._delay_retry('清书投入量或剩余库存无法确认')
            if not self._check_handover_oil():
                return self._delay_retry('石油不足或预计消耗无法确认')
            if self.appear_then_click(DELEGATION_HANDOVER_START, offset=(20, 20), interval=2):
                self._handover_start_duration = required
                self._handover_start_pending = True
                self._handover_preparing = None
                return True
        return False
