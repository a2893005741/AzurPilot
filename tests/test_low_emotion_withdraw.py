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
from module.combat.emotion import Emotion
from module.exception import CampaignEnd, RequestHumanTakeover
from module.map.assets import FLEET_PREPARATION, MAP_PREPARATION, MAP_PREPARATION_CANCEL
from module.map.map_operation import MapOperation


class TestLowEmotionWithdraw(unittest.TestCase):
    EVENT_PRIORITY = 'Event > Event2 > Event3'

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
        emotion.get_recovered_for_battle.return_value = recovered
        campaign = SimpleNamespace(
            low_emotion_withdrawn=True,
            emotion=emotion,
            withdraw=Mock(side_effect=CampaignEnd('Withdraw')),
            _map_battle=5,
        )
        runner = CampaignRun.__new__(CampaignRun)
        runner.__dict__['campaign'] = campaign
        runner.__dict__['config'] = Mock()
        runner.config.task.command = 'Event'
        runner.config.FLEET_2 = 0
        runner.config.SCHEDULER_PRIORITY = self.EVENT_PRIORITY

        self.assertTrue(runner.handle_low_emotion_withdrawal())

        campaign.withdraw.assert_called_once_with(skip_first_screenshot=False)
        emotion.update.assert_called_once_with()
        emotion.record.assert_called_once_with()
        self.assertEqual(fleet.current, 0)
        emotion.get_recovered_for_battle.assert_called_once_with(5)
        runner.config.task_delay.assert_called_once_with(target=recovered)
        runner.config.task_call.assert_called_once_with('Event2', force_call=False)
        runner.config.update.assert_called_once_with()
        self.assertFalse(campaign.low_emotion_withdrawn)

    def test_withdrawal_from_second_event_runs_third_event(self):
        recovered = datetime(2026, 8, 14, 12, 0, 0)
        fleet = Mock()
        emotion = Mock(using_public=False)
        emotion.fleets = [fleet]
        emotion.get_recovered_for_battle.return_value = recovered
        campaign = SimpleNamespace(
            low_emotion_withdrawn=True,
            emotion=emotion,
            withdraw=Mock(side_effect=CampaignEnd('Withdraw')),
            _map_battle=4,
        )
        runner = CampaignRun.__new__(CampaignRun)
        runner.__dict__['campaign'] = campaign
        runner.__dict__['config'] = Mock()
        runner.config.task.command = 'Event2'
        runner.config.FLEET_2 = 0
        runner.config.SCHEDULER_PRIORITY = self.EVENT_PRIORITY

        self.assertTrue(runner.handle_low_emotion_withdrawal())

        runner.config.task_call.assert_called_once_with('Event3', force_call=False)
        runner.config.update.assert_called_once_with()
        emotion.get_recovered_for_battle.assert_called_once_with(4)

    def test_withdrawal_uses_public_fleet_emotion(self):
        recovered = datetime(2026, 8, 14, 12, 0, 0)
        public_fleet = Mock(fleet='Public', current=75)
        public_fleet.get_recovered.return_value = recovered
        fleet_1 = Mock(fleet=1, current=80)
        fleet_2 = Mock(fleet=2, current=90)
        emotion = Mock(using_public=True, public_fleet=public_fleet)
        emotion.fleets = [fleet_1, fleet_2]
        emotion.get_recovered_for_battle.return_value = recovered
        campaign = SimpleNamespace(
            low_emotion_withdrawn=True,
            emotion=emotion,
            withdraw=Mock(side_effect=CampaignEnd('Withdraw')),
            _map_battle=3,
        )
        runner = CampaignRun.__new__(CampaignRun)
        runner.__dict__['campaign'] = campaign
        runner.__dict__['config'] = Mock()
        runner.config.task.command = 'Event3'
        runner.config.FLEET_2 = 2

        self.assertTrue(runner.handle_low_emotion_withdrawal())

        self.assertEqual(public_fleet.current, 0)
        self.assertEqual(fleet_1.current, 80)
        self.assertEqual(fleet_2.current, 90)
        emotion.get_recovered_for_battle.assert_called_once_with(3)
        runner.config.task_delay.assert_called_once_with(target=recovered)

    def test_withdrawal_without_fleet_record_requires_human_takeover(self):
        emotion = Mock(using_public=False)
        emotion.fleets = []
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

        with self.assertRaises(RequestHumanTakeover):
            runner.handle_low_emotion_withdrawal()

        runner.config.task_delay.assert_not_called()

    def test_withdrawal_from_third_event_returns_to_scheduler_queue(self):
        recovered = datetime(2026, 8, 14, 12, 0, 0)
        fleet = Mock()
        emotion = Mock(using_public=False)
        emotion.fleets = [fleet]
        emotion.get_recovered_for_battle.return_value = recovered
        campaign = SimpleNamespace(
            low_emotion_withdrawn=True,
            emotion=emotion,
            withdraw=Mock(side_effect=CampaignEnd('Withdraw')),
            _map_battle=2,
        )
        runner = CampaignRun.__new__(CampaignRun)
        runner.__dict__['campaign'] = campaign
        runner.__dict__['config'] = Mock()
        runner.config.task.command = 'Event3'
        runner.config.FLEET_2 = 0

        self.assertTrue(runner.handle_low_emotion_withdrawal())

        emotion.get_recovered_for_battle.assert_called_once_with(2)
        runner.config.task_delay.assert_called_once_with(target=recovered)
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
        emotion.get_recovered_for_battle.return_value = second_recovered
        campaign = SimpleNamespace(
            low_emotion_withdrawn=True,
            emotion=emotion,
            withdraw=Mock(side_effect=CampaignEnd('Withdraw')),
            _map_battle=6,
        )
        runner = CampaignRun.__new__(CampaignRun)
        runner.__dict__['campaign'] = campaign
        runner.__dict__['config'] = Mock()
        runner.config.task.command = 'Event'
        runner.config.FLEET_2 = 2
        runner.config.SCHEDULER_PRIORITY = self.EVENT_PRIORITY

        self.assertTrue(runner.handle_low_emotion_withdrawal())

        self.assertEqual(fleet_1.current, 0)
        self.assertEqual(fleet_2.current, 0)
        emotion.get_recovered_for_battle.assert_called_once_with(6)
        runner.config.task_delay.assert_called_once_with(target=second_recovered)

    def test_next_event_task_follows_scheduler_priority_configuration(self):
        runner = CampaignRun.__new__(CampaignRun)
        runner.__dict__['config'] = SimpleNamespace(
            SCHEDULER_PRIORITY='Event3 > Main > Event > Event2 > Raid'
        )

        self.assertEqual(runner.get_low_emotion_next_event_task('Event'), 'Event2')
        self.assertIsNone(runner.get_low_emotion_next_event_task('Event2'))

    def test_recovery_for_battle_includes_next_sortie_emotion_cost(self):
        recovered = datetime(2026, 8, 14, 12, 0, 0)
        public_fleet = Mock()
        public_fleet.get_recovered.return_value = recovered
        emotion = Emotion.__new__(Emotion)
        emotion.config = SimpleNamespace(Campaign_Use2xBook=False)
        emotion.using_public = True
        emotion.public_fleet = public_fleet
        emotion.map_is_2x_book = False
        emotion.update = Mock()
        emotion.record = Mock()
        emotion.show = Mock()

        self.assertEqual(emotion.get_recovered_for_battle(5), recovered)

        public_fleet.get_recovered.assert_called_once_with(10)

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

    def test_withdraw_exits_initial_preparation_pages(self):
        for preparation_page in (MAP_PREPARATION, FLEET_PREPARATION):
            with self.subTest(preparation_page=preparation_page):
                operation = MapOperation.__new__(MapOperation)
                operation.device = SimpleNamespace(click=Mock())
                operation.appear = Mock(side_effect=lambda button, **_: button is preparation_page)

                self.assertTrue(operation.handle_enter_map_preparation_cancel())

                operation.device.click.assert_called_once_with(MAP_PREPARATION_CANCEL)

    def test_handle_withdraw_result_falls_back_to_combat_status_popup(self):
        operation = MapOperation.__new__(MapOperation)
        operation.handle_battle_status = Mock(return_value=False)
        operation.handle_exp_info = Mock(return_value=False)
        operation.handle_get_ship = Mock(return_value=False)
        operation.handle_get_items = Mock(return_value=False)
        operation.handle_popup_confirm = Mock(return_value=True)

        self.assertTrue(operation.handle_withdraw_result())

        operation.handle_popup_confirm.assert_called_once_with('COMBAT_STATUS')


if __name__ == '__main__':
    unittest.main()
