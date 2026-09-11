"""上游委托能力与本地执行器的交叉契约。"""

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.campaign.handover_schedule import HandoverSchedule
from module.campaign.operation_handover import (
    OperationHandover, _OCR_COUNT, _OCR_RUNNING_TIME, _parse_count, DELEGATION_BATTLE_MAX,
    DELEGATION_BATTLE_MINUS, DELEGATION_BATTLE_PLUS, DELEGATION_DETAIL_CLOSE,
    DELEGATION_HANDOVER_START, HANDOVER_STOP_CHECK,
)
from module.config.config_updater import ConfigUpdater
from module.map.map_operation import MapOperation


class TestHandoverMerge(unittest.TestCase):
    def runner(self):
        r = OperationHandover.__new__(OperationHandover)
        r.config = SimpleNamespace(
            SERVER='cn', OperationHandover_BattleCount=3,
            OperationHandover_FullDelegationBookCount=2,
            OperationHandover_UseHandoverBook=False,
            OperationHandover_AutoSupplementTime=False,
            OperationHandover_ConsumeAllBook=False,
            OperationHandover_ConsumeAllBookWeekday='sun',
            OperationHandover_ConsumeAllBookTime='10:00',
            OperationHandover_ConsumeAllBookRecord=None,
            OperationHandover_MaintainOverride=False,
            OperationHandover_OilLimit=1000,
            task_delay=Mock(), cross_set=Mock())
        r.device = Mock()
        r.appear = Mock(return_value=False)
        r.appear_then_click = Mock(return_value=True)
        r.handle_popup_confirm = Mock(return_value=False)
        r._close_handover_panel = Mock()
        r._handover_finished = False
        r._read_handover_duration = Mock(return_value=timedelta(minutes=30))
        r._read_handover_remaining = Mock(return_value=timedelta(hours=2))
        r._read_available_books = Mock(return_value=10)
        r._read_selected_books = Mock(return_value=10)
        return r

    def test_configuration_migration_preserves_explicit_values(self):
        updater = ConfigUpdater.__new__(ConfigUpdater)
        updater.args = json.loads(Path('module/config/argument/args.json').read_text(encoding='utf-8'))
        for settings, expected in [({'Count': 16}, 16), ({'Count': 999}, 999),
                                   ({'Count': 999, 'BattleCount': 0}, 0),
                                   ({'BattleCount': 15}, 15)]:
            with self.subTest(settings=settings):
                original = dict(settings, FullDelegationBookCount=3)
                old = {'OperationHandover': {'OperationHandover': original}}
                result = updater.config_update(old)['OperationHandover']['OperationHandover']
                self.assertEqual(result['BattleCount'], expected)
                self.assertEqual(result['FullDelegationBookCount'], 3)
                self.assertNotIn('Count', result)
                self.assertEqual(original, dict(settings, FullDelegationBookCount=3))

    def test_zero_count_without_schedule_disables_only_own_task(self):
        r = self.runner()
        r.config.OperationHandover_BattleCount = 0
        self.assertFalse(r._select_handover_plan())
        r.config.cross_set.assert_called_once_with(keys='OperationHandover.Scheduler.Enable', value=False)

    def test_zero_count_preserves_maintenance_checks(self):
        r = self.runner()
        r.config.OperationHandover_BattleCount = 0
        r.config.OperationHandover_MaintainOverride = True
        r.handover_maintain_state = Mock(return_value=(None, '无公告'))
        with patch('module.campaign.handover_schedule.current_time', return_value=datetime(2026, 9, 11, 12)):
            self.assertFalse(r._select_handover_plan())
        r.config.cross_set.assert_not_called()
        r.config.task_delay.assert_called_once_with(target=datetime(2026, 9, 12))

    def test_maintenance_overrides_weekly_even_with_zero_count(self):
        r = self.runner()
        r.config.OperationHandover_BattleCount = 0
        r.config.OperationHandover_ConsumeAllBook = True
        r.handover_maintain_state = Mock(return_value=(datetime(2026, 9, 13, 11), '维护'))
        with patch('module.campaign.handover_schedule.current_time', return_value=datetime(2026, 9, 13, 10)):
            self.assertFalse(r._select_handover_plan())
            r.config.task_delay.assert_called_with(target=datetime(2026, 9, 13, 10, 50))
        with patch('module.campaign.handover_schedule.current_time', return_value=datetime(2026, 9, 13, 10, 55)):
            self.assertTrue(r._select_handover_plan())
        self.assertTrue(r._handover_maintenance)
        self.assertFalse(r._handover_consume_all)

    def test_weekly_once_and_iso_year_boundary(self):
        r = self.runner()
        r.config.OperationHandover_ConsumeAllBook = True
        with patch('module.campaign.handover_schedule.current_time', return_value=datetime(2027, 1, 3, 12)):
            self.assertTrue(r.handover_consume_all_book_state()[0])
            r.handover_consume_all_book_record()
            self.assertEqual(r.config.OperationHandover_ConsumeAllBookRecord, '2026W53')
            self.assertFalse(r.handover_consume_all_book_state()[0])
        with patch('module.campaign.handover_schedule.current_time', return_value=datetime(2027, 1, 10, 12)):
            self.assertTrue(r.handover_consume_all_book_state()[0])

    def test_weekly_zero_waits_until_trigger(self):
        r = self.runner()
        r.config.OperationHandover_BattleCount = 0
        r.config.OperationHandover_ConsumeAllBook = True
        with patch('module.campaign.handover_schedule.current_time', return_value=datetime(2026, 9, 13, 9)):
            self.assertFalse(r._select_handover_plan())
        r.config.task_delay.assert_called_with(target=datetime(2026, 9, 13, 10))

    def test_maintenance_timezone_and_server_selection(self):
        for server, offset in [('cn', 8), ('tw', 8), ('jp', 9), ('en', -7)]:
            r = self.runner()
            r.config.SERVER = server
            r.config.OperationHandover_MaintainOverride = True
            payload = {'maintenance_date': '2026-09-13', 'start_time': '11:00',
                       'timezone': f'UTC{offset:+d}'}
            response = Mock()
            response.json.return_value = {'data': {'servers': {server: payload}}}
            expected = datetime(2026, 9, 13, 11, tzinfo=timezone(timedelta(hours=offset))).astimezone().replace(tzinfo=None)
            with self.subTest(server=server), patch('module.campaign.handover_schedule.requests.get', return_value=response), \
                    patch('module.campaign.handover_schedule.current_time', return_value=expected - timedelta(hours=1)):
                self.assertEqual(r.handover_maintain_state()[0], expected)

    def test_bad_maintenance_response_falls_back_to_regular_plan(self):
        r = self.runner()
        r.config.OperationHandover_MaintainOverride = True
        for value in [None, [], {'data': 'invalid'}, {'data': {'servers': {'cn': []}}}]:
            with self.subTest(value=value), patch('module.campaign.handover_schedule.requests.get') as get:
                get.return_value.json.return_value = value
                self.assertTrue(r._select_handover_plan())
                self.assertFalse(r._handover_maintenance)

    def test_count_input_boundaries_and_failure(self):
        r = self.runner()
        for count in (15, 16, 999):
            r._read_count = Mock(return_value=1)
            r._input_battle_count = Mock(return_value=True)
            self.assertTrue(r._set_handover_value(_OCR_COUNT, count, DELEGATION_BATTLE_PLUS,
                                                DELEGATION_BATTLE_MINUS, 999, '次数', DELEGATION_BATTLE_MAX))
            r._input_battle_count.assert_called_once_with(count)
        r._input_battle_count.return_value = False
        self.assertFalse(r._set_handover_value(_OCR_COUNT, 999, DELEGATION_BATTLE_PLUS,
                                             DELEGATION_BATTLE_MINUS, 999, '次数', DELEGATION_BATTLE_MAX))
        r.device.click.assert_not_called()

    def test_input_reads_back_and_rejects_out_of_range(self):
        r = self.runner()
        r.appear.return_value = True
        r.loop = Mock(return_value=[None])
        for count in (0, -1, 1000):
            self.assertFalse(r._input_battle_count(count))
        r.device.adb_shell.assert_not_called()
        r._read_count = Mock(return_value=16)
        self.assertTrue(r._input_battle_count(16))
        r._read_count.return_value = 15
        self.assertFalse(r._input_battle_count(16))

    def test_oil_unknown_and_shortage_never_start(self):
        r = self.runner()
        with patch('module.campaign.operation_handover.crop'), patch('module.campaign.operation_handover.OCR_MODEL') as model:
            for oil, cost, expected in [(None, '500', False), (5000, '', False),
                                        (500, '400', False), (5000, '6,000', False), (5000, '400', True)]:
                r._handover_oil = oil
                model.azur_lane.ocr_for_single_line.return_value = cost
                self.assertEqual(r._check_handover_oil(), expected)
        r._begin_handover_preparation()
        r._handover_preparing = 'final'
        r._check_handover_oil = Mock(return_value=False)
        r._prepare_handover()
        r.appear_then_click.assert_not_called()
        r._close_handover_panel.assert_called_once()

    def test_count_parser_never_uses_partial_ocr_result(self):
        for value in ('a100', '100?', '1,2', '', None):
            self.assertIsNone(_parse_count(value))
        self.assertEqual(_parse_count(0), 0)
        self.assertEqual(_parse_count('1,500'), 1500)

    def test_consume_selects_books_before_time_and_recomputes_after_exchange(self):
        r = self.runner()
        r._handover_consume_all = True
        r.config.OperationHandover_AutoSupplementTime = True
        r._begin_handover_preparation()
        self.assertEqual(r._handover_preparing, 'books')
        self.assertTrue(r._handover_use_max)
        r._handover_preparing = 'consume_count'
        r._input_battle_count = Mock(return_value=True)
        r._prepare_handover()
        r._input_battle_count.assert_called_once_with(10)
        self.assertEqual(r._handover_preparing, 'time')
        r._prepare_handover()
        self.assertEqual(r._handover_preparing, 'final')
        r._handover_preparing = 'exchange_verify'
        r._handover_available = timedelta(0)
        r.appear.return_value = True
        r._prepare_handover()
        self.assertEqual(r._handover_preparing, 'books')
        self.assertFalse(r._handover_consume_count_ready)

    def test_weekly_record_requires_observed_start(self):
        r = self.runner()
        r._handover_consume_all = True
        r._handover_start_pending = True
        r._handover_start_duration = timedelta(minutes=30)
        r.handle_handover_panel()
        self.assertIsNone(r.config.OperationHandover_ConsumeAllBookRecord)
        r.appear.side_effect = lambda button, **kw: button in (HANDOVER_STOP_CHECK, DELEGATION_DETAIL_CLOSE)
        with patch('module.campaign.handover_schedule.current_time', return_value=datetime(2026, 9, 13, 12)):
            r.handle_handover_panel()
        self.assertEqual(r.config.OperationHandover_ConsumeAllBookRecord, '2026W37')

    def test_conflict_uses_live_duration_never_weekly_next_run(self):
        r = MapOperation.__new__(MapOperation)
        r.device = Mock()
        r.config = Mock()
        r.config.cross_get.return_value = datetime(2026, 9, 20)
        r.appear = Mock(return_value=True)
        now = datetime(2026, 9, 13, 12)
        with patch('module.map.map_operation.current_time', return_value=now), \
                patch.object(_OCR_RUNNING_TIME, 'ocr', return_value='00:07:00'):
            self.assertEqual(r.handover_conflict_delay(), now + timedelta(minutes=8))
        r.config.cross_get.assert_not_called()
        with patch('module.map.map_operation.current_time', return_value=now), \
                patch.object(_OCR_RUNNING_TIME, 'ocr', return_value='unknown'):
            self.assertEqual(r.handover_conflict_delay(), now + timedelta(minutes=15))


if __name__ == '__main__':
    unittest.main()
