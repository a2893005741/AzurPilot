"""用截图阶段替身验证补时顺序、库存预留与 MAX 确认。"""

import unittest
import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

from module.campaign.operation_handover import OperationHandover
from module.campaign.operation_handover import _parse_duration
from module.config.config_updater import ConfigUpdater
from module.campaign.assets import DELEGATION_BOOK_MAX, DELEGATION_BOOK_MINUS
from module.map.assets import HANDOVER_BOOK_ITEM


class TestHandoverPreparation(unittest.TestCase):
    def test_old_configuration_keeps_values_and_new_switches_off(self):
        updater = ConfigUpdater.__new__(ConfigUpdater)
        updater.args = json.loads(Path('module/config/argument/args.json').read_text(encoding='utf-8'))
        result = updater.config_update({'OperationHandover': {
            'OperationHandover': {'BattleCount': 7, 'FullDelegationBookCount': 3},
            'Scheduler': {'SuccessInterval': '45-60'},
        }})['OperationHandover']
        self.assertEqual(result['OperationHandover'], {
            'BattleCount': 7, 'FullDelegationBookCount': 3,
            'AutoSupplementTime': False, 'UseHandoverBook': False,
        })
        self.assertEqual(result['Scheduler']['SuccessInterval'], '30-60')
        self.assertFalse(result['Campaign']['UseAutoSearch'])

    def test_invalid_duration_is_not_a_zero_time_success(self):
        for value in ('', 'garbage', '01:60:00', '00:00:99', 'x00:01:00'):
            self.assertIsNone(_parse_duration(value))
        self.assertEqual(_parse_duration('00:00:00'), timedelta(0))

    def make_runner(self, auto=False, maximum=False, fixed=2, stock=5):
        runner = OperationHandover.__new__(OperationHandover)
        runner.config = Mock(
            OperationHandover_FullDelegationBookCount=fixed,
            OperationHandover_UseHandoverBook=maximum,
            OperationHandover_AutoSupplementTime=auto)
        runner._handover_finished = False
        runner._read_available_books = Mock(return_value=stock)
        runner._read_exchange_books = Mock(return_value=stock)
        runner._read_selected_books = Mock(return_value=0)
        runner._read_handover_duration = Mock(return_value=timedelta(hours=1))
        runner._read_handover_remaining = Mock(return_value=timedelta(hours=2))
        runner._set_fixed_handover_books = Mock(return_value=True)
        runner.appear = Mock(return_value=True)
        runner.appear_then_click = Mock(return_value=True)
        runner.handle_popup_confirm = Mock(return_value=True)
        runner.handle_popup_cancel = Mock(return_value=True)
        runner._begin_handover_preparation()
        return runner

    def test_all_switch_combinations_without_deficit(self):
        for auto in (False, True):
            for maximum in (False, True):
                with self.subTest(auto=auto, maximum=maximum):
                    r = self.make_runner(auto, maximum)
                    r._prepare_handover()
                    self.assertEqual(r._handover_preparing, 'books')
                    r._prepare_handover()
                    if maximum:
                        r._set_fixed_handover_books.assert_not_called()
                        self.assertEqual(r._handover_preparing, 'max_click')
                    else:
                        r._set_fixed_handover_books.assert_called_once_with(2)

    def test_reserve_and_rounding_before_any_exchange(self):
        for seconds, needed in ((0, 0), (1, 1), (3600, 1), (3601, 2)):
            for enough in (False, True):
                with self.subTest(seconds=seconds, enough=enough):
                    r = self.make_runner(auto=True, stock=2 + needed - (not enough))
                    r._read_handover_duration.return_value = timedelta(seconds=seconds)
                    r._read_handover_remaining.return_value = timedelta(0)
                    r._prepare_handover()
                    r.appear_then_click.assert_not_called()
                    self.assertEqual(r._handover_finished, not enough)

    def test_unknown_stock_retries_without_consumption(self):
        r = self.make_runner(auto=True, stock=None)
        r._prepare_handover()
        r.config.task_delay.assert_called_once_with(minute=30)
        r.appear_then_click.assert_not_called()

    def test_exchange_confirms_one_book_then_waits_for_time(self):
        r = self.make_runner(auto=True)
        r._read_handover_remaining.return_value = timedelta(0)
        for _ in range(4):
            r._prepare_handover()
        self.assertEqual(r._handover_preparing, 'exchange_verify')
        r.appear_then_click.assert_called_once_with(HANDOVER_BOOK_ITEM, offset=(20, 20), interval=2)
        r._handover_observe_timer = Mock(reached=Mock(return_value=False))
        r._prepare_handover()
        self.assertEqual(r._handover_preparing, 'exchange_verify')
        r.handle_popup_confirm.assert_called_once()
        r._read_handover_remaining.return_value = timedelta(hours=1)
        r._prepare_handover()
        self.assertEqual(r._handover_preparing, 'books')

    def test_missing_credit_does_not_confirm_twice(self):
        r = self.make_runner(auto=True)
        r._read_handover_remaining.return_value = timedelta(0)
        for _ in range(4):
            r._prepare_handover()
        r._handover_observe_timer = Mock(reached=Mock(return_value=True))
        r._prepare_handover()
        r.config.task_delay.assert_called_once_with(minute=30)
        r.handle_popup_confirm.assert_called_once()

    def test_already_max_reduces_then_restores_dynamic_max(self):
        r = self.make_runner(maximum=True)
        r._read_selected_books.return_value = 5
        r._prepare_handover()
        r._prepare_handover()
        r._prepare_handover()
        r.appear_then_click.assert_called_with(DELEGATION_BOOK_MINUS, offset=(20, 20), interval=2)
        r._read_selected_books.return_value = 4
        r._prepare_handover()
        r._prepare_handover()
        r.appear_then_click.assert_called_with(DELEGATION_BOOK_MAX, offset=(20, 20), interval=2)
        r._read_selected_books.return_value = 5
        r._prepare_handover()
        r._handover_observe_timer = Mock(reached=Mock(return_value=True))
        r._prepare_handover()
        self.assertEqual(r._handover_preparing, 'final')

    def test_no_effect_max_retries_and_zero_stock_is_valid(self):
        r = self.make_runner(maximum=True)
        for _ in range(4):
            r._prepare_handover()
        r._handover_observe_timer = Mock(reached=Mock(return_value=True))
        r._prepare_handover()
        r.config.task_delay.assert_called_once_with(minute=30)
        r = self.make_runner(maximum=True, stock=0)
        r._prepare_handover()
        r._prepare_handover()
        self.assertEqual(r._handover_preparing, 'final')

    def test_final_duration_is_used_after_book_adjustment(self):
        r = self.make_runner()
        r._prepare_handover()
        r._prepare_handover()
        r._read_handover_duration.return_value = timedelta(minutes=7)
        r._prepare_handover()
        self.assertEqual(r._handover_start_duration, timedelta(minutes=7))
        self.assertTrue(r._handover_start_pending)

    def test_final_ocr_failure_never_starts(self):
        r = self.make_runner()
        r._prepare_handover()
        r._prepare_handover()
        r._read_handover_duration.return_value = None
        r._prepare_handover()
        r.appear_then_click.assert_not_called()
        r.config.task_delay.assert_called_once_with(minute=30)
