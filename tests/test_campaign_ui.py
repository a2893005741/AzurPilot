import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

import numpy as np

from module.base.button import Button
from module.base.utils import load_image
from module.campaign.assets import (
    EVENT_20260908_STAGE_DETAIL_CLOSE,
    EVENT_20260908_STAGE_MODE_HARD,
    EVENT_20260908_STAGE_MODE_NORMAL,
)
from module.campaign.campaign_ui import CampaignUI


class TestCampaignUI(unittest.TestCase):
    def _finish_switch(self, ui, name):
        result = ui.campaign_switch_stage_mode(name)
        for _ in range(8):
            if result is not None:
                return result
            ui.device.screenshot()
            result = ui.campaign_switch_stage_mode(name)
        self.fail('模式切换未完成')

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
                return detail_close_calls < 4
            return button is EVENT_20260908_STAGE_MODE_NORMAL

        ui.appear = Mock(side_effect=appear)
        ui._appear_event_stage_mode_button = Mock(return_value=True)

        result = self._finish_switch(ui, 'b1')

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

    def _fixture(self, name):
        return load_image(str(Path(__file__).parent / 'fixtures' / 'campaign_mode' / f'{name}.png'))

    def _image_ui(self, image):
        ui = object.__new__(CampaignUI)
        ui.config = Mock(MAP_CHAPTER_SWITCH_20241219=True, MAP_HAS_MODE_SWITCH=False, BUTTON_OFFSET=(5, 5))
        ui.device = Mock(image=image)
        ui.interval_timer = {}
        return ui

    def test_mode_buttons_match_selected_unselected_and_bonus_states(self):
        for name in ('a3', 'b3', 'd3', 'c2_bonus'):
            for button in (EVENT_20260908_STAGE_MODE_NORMAL, EVENT_20260908_STAGE_MODE_HARD):
                with self.subTest(frame=name, button=button.name):
                    ui = self._image_ui(self._fixture(name))
                    self.assertTrue(ui._appear_event_stage_mode_button(button))
                    # 点击必须落在对应模式按钮内，不能复用失败匹配留下的偏移。
                    left, top, right, bottom = button.button
                    bound = (150, 575, 274, 622) if button is EVENT_20260908_STAGE_MODE_NORMAL else (274, 575, 400, 622)
                    self.assertTrue(bound[0] <= left < right <= bound[2])
                    self.assertTrue(bound[1] <= top < bottom <= bound[3])

    def test_mode_buttons_reject_stage_list_and_empty_image(self):
        for image in (self._fixture('stage_list'), np.zeros((720, 1280, 3), dtype=np.uint8)):
            ui = self._image_ui(image)
            for button in (EVENT_20260908_STAGE_MODE_NORMAL, EVENT_20260908_STAGE_MODE_HARD):
                self.assertFalse(ui._appear_event_stage_mode_button(button))

    def test_mode_switch_replays_both_directions_and_returns_fresh_entrance(self):
        for source, target, frame, switched in (('a3', 'c3', 'a3', 'd3'), ('d3', 'b3', 'd3', 'b3')):
            with self.subTest(target=target):
                ui = self._image_ui(self._fixture('stage_list'))
                old = Button(area=(800, 300, 860, 330), color=(), button=(800, 300, 860, 330), name=source)
                fresh = Button(area=(810, 300, 870, 330), color=(), button=(810, 300, 870, 330), name=target)
                ui.stage_entrance = {source: old}
                # 模式按钮点击后弹窗仍在；关闭后才允许更新 OCR 入口。
                frames = iter([self._fixture(frame), self._fixture(switched), self._fixture('stage_list'), self._fixture('stage_list')])
                def screenshot():
                    ui.device.image = next(frames)
                def refresh(image):
                    np.testing.assert_array_equal(image, self._fixture('stage_list'))
                    ui.stage_entrance = {target: fresh}
                ui.device.screenshot.side_effect = screenshot
                ui._get_stage_name = Mock(side_effect=refresh)

                self.assertIs(self._finish_switch(ui, target), fresh)
                mode = EVENT_20260908_STAGE_MODE_HARD if target == 'c3' else EVENT_20260908_STAGE_MODE_NORMAL
                self.assertEqual([call.args[0] for call in ui.device.click.call_args_list],
                                 [old, mode, EVENT_20260908_STAGE_DETAIL_CLOSE])
                ui._get_stage_name.assert_called_once()

    def test_missing_mode_button_does_not_click_guessed_position(self):
        image = self._fixture('a3')
        image[565:630, 140:425] = 0
        ui = self._image_ui(image)
        old = Button(area=(800, 300, 860, 330), color=(), button=(800, 300, 860, 330), name='a3')
        ui.stage_entrance = {'a3': old}
        with patch('module.campaign.campaign_ui.Timer') as timer:
            timer.return_value.start.return_value.reached.return_value = True
            self.assertIsNone(ui.campaign_switch_stage_mode('c3'))
            self.assertIsNone(ui.campaign_switch_stage_mode('c3'))
        ui.device.click.assert_called_once_with(old)
        ui.device.screenshot.assert_not_called()

    def test_d3_3_reuses_d3_entry_for_mode_switch(self):
        ui = object.__new__(CampaignUI)
        ui.config = Mock(MAP_HAS_MODE_SWITCH=False)
        entrance = Button(area=(100, 100, 120, 120), color=(1, 1, 1), button=(100, 100, 120, 120), name='d3')
        ui.stage_entrance = {'d3': entrance}
        self.assertEqual(ui.campaign_stage_ui_name('d3_3'), 'd3')
        self.assertIs(ui.campaign_get_entrance('d3_3'), entrance)
        self.assertEqual(entrance.name, 'd3_3')

    def test_ensure_campaign_ui_accepts_d3_alias_with_legacy_mode_switch(self):
        ui = self._image_ui(self._fixture('stage_list'))
        ui.config.MAP_HAS_MODE_SWITCH = True
        entrance = Button(area=(100, 100, 120, 120), color=(), button=(100, 100, 120, 120), name='d3')
        ui.stage_entrance = {'d3': entrance}
        ui.campaign_set_chapter = Mock()
        ui.handle_campaign_ui_additional = Mock(return_value=False)
        self.assertTrue(ui.ensure_campaign_ui('d3_3'))
        self.assertIs(ui.ENTRANCE, entrance)
        self.assertEqual(entrance.name, 'd3_3')

    def test_parent_loop_handles_popup_during_detail_switch_and_preserves_alias(self):
        ui = self._image_ui(self._fixture('stage_list'))
        old = Button(area=(800, 300, 860, 330), color=(), button=(800, 300, 860, 330), name='b3')
        fresh = Button(area=(810, 300, 870, 330), color=(), button=(810, 300, 870, 330), name='d3')
        ui.stage_entrance = {'b3': old}
        ui.campaign_set_chapter = Mock()
        ui.handle_campaign_ui_additional = Mock(return_value=False)
        ui.ui_additional = Mock(side_effect=[True, False, False, False])
        frames = iter([self._fixture('b3'), self._fixture('b3'), self._fixture('d3'), self._fixture('stage_list')])
        ui.device.screenshot.side_effect = lambda: setattr(ui.device, 'image', next(frames))
        ui._get_stage_name = Mock(side_effect=lambda image: setattr(ui, 'stage_entrance', {'d3': fresh}))
        self.assertTrue(ui.ensure_campaign_ui('d3_3'))
        self.assertIs(ui.ENTRANCE, fresh)
        self.assertEqual(fresh.name, 'd3_3')
        ui.campaign_set_chapter.assert_called_once()
        self.assertEqual(ui.ui_additional.call_count, 4)
        self.assertEqual([item.args[0] for item in ui.device.click.call_args_list],
                         [old, EVENT_20260908_STAGE_MODE_HARD, EVENT_20260908_STAGE_DETAIL_CLOSE])

    def test_additional_handler_leaves_owned_detail_open(self):
        ui = self._image_ui(self._fixture('b3'))
        ui._stage_mode_switch_phase = 'mode'
        self.assertFalse(ui.handle_campaign_ui_additional())
        ui.device.click.assert_not_called()
