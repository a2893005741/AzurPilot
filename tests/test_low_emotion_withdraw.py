from datetime import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

# 本地旧虚拟环境的 RapidOCR 仍未提供源码要求的 PPOCRV6 枚举。
# 仅为加载待测战役模块补齐别名，不影响生产运行时的依赖版本。
from rapidocr import OCRVersion

if not hasattr(OCRVersion, 'PPOCRV6'):
    OCRVersion.PPOCRV6 = OCRVersion.PPOCRV5

from module.campaign.campaign_base import CampaignBase
from module.campaign.run import CampaignRun
from module.exception import CampaignEnd
from module.map.map_operation import MapOperation


class TestLowEmotionWithdraw(unittest.TestCase):
    def test_calculate_mode_cancels_then_exits_combat_preparation(self):
        campaign = CampaignBase.__new__(CampaignBase)
        campaign.config = SimpleNamespace(Emotion_Mode='calculate')
        campaign.handle_popup_cancel = Mock(return_value=True)
        campaign.withdraw = Mock()

        with self.assertRaises(CampaignEnd):
            campaign.handle_combat_low_emotion()

        campaign.handle_popup_cancel.assert_called_once_with('IGNORE_LOW_EMOTION')
        campaign.withdraw.assert_not_called()
        self.assertTrue(campaign.low_emotion_withdrawn)

    def test_non_calculate_mode_keeps_original_confirm_behavior(self):
        campaign = CampaignBase.__new__(CampaignBase)
        campaign.config = SimpleNamespace(Emotion_Mode='calculate_ignore')
        campaign.__dict__['emotion'] = SimpleNamespace(is_ignore=True)
        campaign.handle_popup_cancel = Mock()
        campaign.handle_popup_confirm = Mock(return_value=True)
        campaign.interval_reset = Mock()

        self.assertTrue(campaign.handle_combat_low_emotion())

        campaign.handle_popup_cancel.assert_not_called()
        campaign.handle_popup_confirm.assert_called_once_with('IGNORE_LOW_EMOTION')

    def test_withdrawal_delays_current_task_to_emotion_recovery(self):
        recovered = datetime(2026, 8, 14, 12, 0, 0)
        fleet = Mock()
        fleet.fleet = 1
        fleet.current = 75
        fleet.get_recovered.return_value = recovered
        emotion = Mock(using_public=False)
        emotion.fleets = [fleet, Mock()]
        campaign = SimpleNamespace(
            low_emotion_withdrawn=True,
            emotion=emotion,
            withdraw=Mock(side_effect=CampaignEnd('Withdraw')),
        )
        runner = CampaignRun.__new__(CampaignRun)
        runner.__dict__['campaign'] = campaign
        runner.__dict__['config'] = Mock()
        runner.config.task.command = 'Event'
        runner.config.FLEET_2 = 0

        self.assertTrue(runner.handle_low_emotion_withdrawal())

        campaign.withdraw.assert_called_once_with(skip_first_screenshot=False)
        emotion.update.assert_called_once_with()
        emotion.record.assert_called_once_with()
        self.assertEqual(fleet.current, 0)
        fleet.get_recovered.assert_called_once_with()
        runner.config.task_delay.assert_called_once_with(target=recovered)
        runner.config.task_call.assert_called_once_with('Event2', force_call=False)
        runner.config.update.assert_called_once_with()
        self.assertFalse(campaign.low_emotion_withdrawn)

    def test_withdrawal_from_second_event_runs_third_event(self):
        fleet = Mock()
        fleet.get_recovered.return_value = datetime(2026, 8, 14, 12, 0, 0)
        emotion = Mock(using_public=False)
        emotion.fleets = [fleet]
        campaign = SimpleNamespace(
            low_emotion_withdrawn=True,
            emotion=emotion,
            withdraw=Mock(side_effect=CampaignEnd('Withdraw')),
        )
        runner = CampaignRun.__new__(CampaignRun)
        runner.__dict__['campaign'] = campaign
        runner.__dict__['config'] = Mock()
        runner.config.task.command = 'Event2'
        runner.config.FLEET_2 = 0

        self.assertTrue(runner.handle_low_emotion_withdrawal())

        runner.config.task_call.assert_called_once_with('Event3', force_call=False)
        runner.config.update.assert_called_once_with()

    def test_withdrawal_from_third_event_returns_to_scheduler_queue(self):
        fleet = Mock()
        fleet.get_recovered.return_value = datetime(2026, 8, 14, 12, 0, 0)
        emotion = Mock(using_public=False)
        emotion.fleets = [fleet]
        campaign = SimpleNamespace(
            low_emotion_withdrawn=True,
            emotion=emotion,
            withdraw=Mock(side_effect=CampaignEnd('Withdraw')),
        )
        runner = CampaignRun.__new__(CampaignRun)
        runner.__dict__['campaign'] = campaign
        runner.__dict__['config'] = Mock()
        runner.config.task.command = 'Event3'
        runner.config.FLEET_2 = 0

        self.assertTrue(runner.handle_low_emotion_withdrawal())

        runner.config.task_delay.assert_called_once_with(target=fleet.get_recovered.return_value)
        runner.config.task_call.assert_not_called()
        runner.config.update.assert_not_called()

    def test_withdrawal_delays_both_configured_fleets(self):
        first_recovered = datetime(2026, 8, 14, 12, 0, 0)
        second_recovered = datetime(2026, 8, 14, 12, 12, 0)
        fleet_1 = Mock(fleet=1, current=75)
        fleet_1.get_recovered.return_value = first_recovered
        fleet_2 = Mock(fleet=2, current=90)
        fleet_2.get_recovered.return_value = second_recovered
        emotion = Mock(using_public=False)
        emotion.fleets = [fleet_1, fleet_2]
        campaign = SimpleNamespace(
            low_emotion_withdrawn=True,
            emotion=emotion,
            withdraw=Mock(side_effect=CampaignEnd('Withdraw')),
        )
        runner = CampaignRun.__new__(CampaignRun)
        runner.__dict__['campaign'] = campaign
        runner.__dict__['config'] = Mock()
        runner.config.task.command = 'Event'
        runner.config.FLEET_2 = 2

        self.assertTrue(runner.handle_low_emotion_withdrawal())

        self.assertEqual(fleet_1.current, 0)
        self.assertEqual(fleet_2.current, 0)
        runner.config.task_delay.assert_called_once_with(target=second_recovered)

    def test_withdraw_processes_battle_result_before_waiting_for_stage(self):
        operation = MapOperation.__new__(MapOperation)
        operation.device = SimpleNamespace(screenshot=Mock())
        operation.handle_battle_status = Mock(side_effect=[True, False])
        operation.handle_exp_info = Mock(return_value=False)
        operation.handle_get_ship = Mock(return_value=False)
        operation.handle_get_items = Mock(return_value=False)
        operation.handle_popup_confirm = Mock(return_value=False)
        operation.appear_then_click = Mock(return_value=False)
        operation.handle_auto_search_exit = Mock(return_value=False)
        operation.appear = Mock(return_value=False)
        operation.handle_in_stage = Mock(return_value=True)

        with self.assertRaises(CampaignEnd):
            operation.withdraw(skip_first_screenshot=False)

        operation.handle_battle_status.assert_called()
        operation.handle_in_stage.assert_called_once_with()

    def test_withdraw_exits_battle_preparation_before_opening_withdraw_menu(self):
        operation = MapOperation.__new__(MapOperation)
        operation.device = SimpleNamespace(click=Mock())
        operation.appear = Mock(return_value=True)

        self.assertTrue(operation.handle_withdraw_battle_preparation())

        operation.device.click.assert_called_once()


if __name__ == '__main__':
    unittest.main()
