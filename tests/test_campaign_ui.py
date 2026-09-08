import unittest
from unittest.mock import Mock

from module.base.button import Button
from module.campaign.assets import (
    EVENT_20260908_STAGE_DETAIL_CLOSE,
    EVENT_20260908_STAGE_MODE_NORMAL,
)
from module.campaign.campaign_ui import CampaignUI


class TestCampaignUI(unittest.TestCase):
    def _make_ui(self):
        ui = object.__new__(CampaignUI)
        ui.config = Mock(MAP_CHAPTER_SWITCH_20241219=True)
        ui.ui_goto_event = Mock()
        ui.campaign_ensure_mode_20241219 = Mock()
        ui.campaign_ensure_aside_20241219 = Mock()
        ui.campaign_ensure_chapter = Mock()
        return ui

    def test_event_normal_stage_resets_stale_hard_mode(self):
        ui = self._make_ui()

        self.assertTrue(ui.campaign_set_chapter_20241219('b', '1', mode='hard'))

        ui.config.override.assert_called_once_with(Campaign_Mode='normal')
        ui.campaign_ensure_aside_20241219.assert_called_once_with('part2')
        ui.campaign_ensure_chapter.assert_called_once_with('b')

    def test_event_hard_stage_sets_hard_mode(self):
        ui = self._make_ui()

        self.assertTrue(ui.campaign_set_chapter_20241219('d', '1', mode='normal'))

        ui.config.override.assert_called_once_with(Campaign_Mode='hard')
        ui.campaign_ensure_aside_20241219.assert_called_once_with('part2')
        ui.campaign_ensure_chapter.assert_called_once_with('d')

    def test_missing_normal_stage_switches_from_hard_detail(self):
        ui = object.__new__(CampaignUI)
        ui.config = Mock(MAP_CHAPTER_SWITCH_20241219=True, MAP_HAS_MODE_SWITCH=False)
        entrance = Button(area=(100, 100, 120, 120), color=(1, 1, 1), button=(100, 100, 120, 120), name='d1')
        ui.stage_entrance = {'d1': entrance}
        ui.device = Mock()
        def refresh_stage_entrance(image):
            entrance.name = 'b1'
            ui.stage_entrance = {'b1': entrance}

        ui._get_stage_name = Mock(side_effect=refresh_stage_entrance)
        detail_close_calls = 0

        def appear(button, **kwargs):
            nonlocal detail_close_calls
            if button is EVENT_20260908_STAGE_DETAIL_CLOSE:
                detail_close_calls += 1
                return detail_close_calls < 3
            return button is EVENT_20260908_STAGE_MODE_NORMAL

        ui.appear = Mock(side_effect=appear)

        result = ui.campaign_switch_stage_mode('b1')

        self.assertIs(result, entrance)
        self.assertEqual(result.name, 'b1')
        self.assertEqual(ui.device.click.call_args_list[0].args, (entrance,))
        self.assertEqual(ui.device.click.call_args_list[1].args, (EVENT_20260908_STAGE_MODE_NORMAL,))
        self.assertEqual(ui.device.click.call_args_list[2].args, (EVENT_20260908_STAGE_DETAIL_CLOSE,))
        self.assertEqual(len(ui.device.click.call_args_list), 3)

    def test_campaign_detail_popup_is_closed_as_additional_ui(self):
        ui = object.__new__(CampaignUI)
        ui.appear = Mock(side_effect=lambda button, **kwargs: button is EVENT_20260908_STAGE_DETAIL_CLOSE)
        ui.device = Mock()

        self.assertTrue(ui.handle_campaign_ui_additional())
        ui.device.click.assert_called_once_with(EVENT_20260908_STAGE_DETAIL_CLOSE)
