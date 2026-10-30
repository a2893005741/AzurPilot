"""用真实弹窗及延迟转场回放计划作战确认，不连接设备。"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from module.base.utils import load_image
from module.exception import GameStuckError
from module.handler.assets import POPUP_CONFIRM
from module.os_handler.assets import STRATEGIC_SEARCH_POPUP_CHECK
from module.os_handler.strategic import StrategicSearchHandler
from tests.test_opsi_cl1_speed import VirtualClock


FIXTURES = Path(__file__).parent / 'fixtures' / 'opsi_auto_search'


class TestStrategicSearchConfirm(unittest.TestCase):
    def make_handler(self, image):
        handler = StrategicSearchHandler.__new__(StrategicSearchHandler)
        handler.config = SimpleNamespace(SERVER='cn')
        handler.device = Mock(image=image)
        handler.interval_timer = {}
        return handler

    @staticmethod
    def panel_frame():
        # 资源图只保留各自识别区域，合成标题与两个按钮模拟初始面板。
        return np.maximum.reduce([
            load_image('assets/cn/os_handler/STRATEGIC_SEARCH_POPUP_CHECK.png'),
            load_image('assets/cn/handler/POPUP_CANCEL.png'),
            load_image('assets/cn/handler/POPUP_CONFIRM.png'),
        ])

    def test_recall_after_panel_confirmation_waits_for_map(self):
        """开始后出现另一层弹窗，冷却及转场期间不能提前结束。"""
        frames = {
            'panel': self.panel_frame(),
            'recall': load_image(str(FIXTURES / 'strategic_search_recall.png')),
            'map': load_image('assets/cn/os_handler/IN_MAP.png'),
        }
        handler = self.make_handler(frames['recall'])
        self.assertFalse(handler.appear(STRATEGIC_SEARCH_POPUP_CHECK, offset=(20, 20)))
        self.assertFalse(handler.is_in_map())
        self.assertTrue(handler.appear(POPUP_CONFIRM, offset=(30, 30)))
        handler.device.image = frames['panel']
        clock = VirtualClock()
        state = SimpleNamespace(phase='panel', clicked_at=None, screenshots=0)
        clicks = []

        def screenshot():
            clock.now += 0.2
            state.screenshots += 1
            if state.screenshots > 45:
                self.fail('召回弹窗未被确认或尚未返回地图')
            if state.phase == 'recall' and state.clicked_at is not None \
                    and clock.now - state.clicked_at >= 3.2:
                state.phase = 'map'
            handler.device.image = frames[state.phase]

        def click(button):
            self.assertIs(button, POPUP_CONFIRM)
            clicks.append((state.phase, clock.now))
            if state.phase == 'panel':
                state.phase = 'recall'
            else:
                self.assertEqual(state.phase, 'recall')
                if state.clicked_at is None:
                    state.clicked_at = clock.now

        handler.device.screenshot.side_effect = screenshot
        handler.device.click.side_effect = click
        with patch('module.base.timer.time', clock):
            self.assertTrue(handler.strategic_search_confirm())
        self.assertEqual(state.phase, 'map')
        self.assertEqual([phase for phase, _ in clicks], ['panel', 'recall', 'recall'])
        self.assertTrue(all(later[1] - earlier[1] >= 2
                            for earlier, later in zip(clicks, clicks[1:])))
        self.assertGreaterEqual(clock.now - state.clicked_at, 3.2)

    def test_map_without_popup_returns_without_clicks(self):
        handler = self.make_handler(load_image('assets/cn/os_handler/IN_MAP.png'))
        handler.device.screenshot.side_effect = AssertionError('已在地图，不应继续等待')
        self.assertTrue(handler.strategic_search_confirm())
        handler.device.click.assert_not_called()

    def test_device_stuck_error_propagates(self):
        # 未见过计划作战面板时不确认未知弹窗，因此从面板起步才会产生首次点击。
        handler = self.make_handler(self.panel_frame())
        handler.device.screenshot.side_effect = GameStuckError('测试设备卡死')
        with self.assertRaises(GameStuckError):
            handler.strategic_search_confirm()
        handler.device.click.assert_called_once_with(POPUP_CONFIRM)


if __name__ == '__main__':
    unittest.main()
