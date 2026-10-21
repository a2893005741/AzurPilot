"""用真实结算截图验证大世界地图扫描中的战后收尾，不连接游戏。"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from module.base.utils import load_image
from module.combat.assets import BATTLE_STATUS_S, EXP_INFO_S
from module.exception import MapDetectionError
from module.map.camera import Camera
from module.os.map import OSMap
from tests.test_opsi_cl1_speed import VirtualClock


FIXTURES = Path(__file__).parent / 'fixtures' / 'opsi_auto_search'


class TestOpsiCameraSettlement(unittest.TestCase):
    def make_handler(self):
        handler = OSMap.__new__(OSMap)
        handler.config = SimpleNamespace(SERVER='cn')
        handler.device = Mock(image=load_image(str(FIXTURES / 'battle_status_s.png')))
        handler.interval_timer = {}
        handler.is_in_map = Mock(return_value=False)
        handler.is_combat_executing = Mock(return_value=False)
        handler.is_combat_loading = Mock(return_value=False)
        handler.view = SimpleNamespace(center_offset=(0.5, 0.5))
        handler._update_view_data = Mock()
        return handler

    def test_camera_waits_for_s_rank_then_confirms_exp_before_accepting_map(self):
        handler = self.make_handler()
        clock = VirtualClock()
        state = SimpleNamespace(phase='rank', screenshots=0, confirmed_at=None)
        frames = {
            'rank': handler.device.image,
            'exp': load_image(str(FIXTURES / 'exp_info_delayed.png')),
        }

        def screenshot():
            clock.now += 0.2
            state.screenshots += 1
            if state.screenshots > 160:
                self.fail('结算处理未能返回地图')
            if state.confirmed_at is not None and clock.now - state.confirmed_at >= 3.2:
                state.phase = 'map'
            if state.phase in frames:
                handler.device.image = frames[state.phase]

        def click(button):
            if state.phase == 'rank':
                self.assertIs(button, BATTLE_STATUS_S)
                self.assertGreaterEqual(clock.now, 120, '必须保留原有 S 评价等待时间')
                state.phase = 'exp'
            else:
                self.assertEqual(state.phase, 'exp')
                self.assertIs(button, EXP_INFO_S)
                if state.confirmed_at is None:
                    state.confirmed_at = clock.now

        def update_view():
            if state.phase != 'map':
                raise MapDetectionError('结算尚未完成，不能解析地图')
            return True

        handler.device.screenshot.side_effect = screenshot
        handler.device.click.side_effect = click
        handler.is_in_map.side_effect = lambda: state.phase == 'map'
        with patch('module.base.timer.time', clock), \
                patch.object(Camera, '_update_view', side_effect=update_view) as parent:
            handler.update()

        self.assertEqual(state.phase, 'map')
        self.assertEqual(handler.device.click.call_args_list, [call(BATTLE_STATUS_S), call(EXP_INFO_S), call(EXP_INFO_S)])
        parent.assert_called_once_with()
        handler._update_view_data.assert_called_once_with()

    def test_map_and_active_battle_do_not_receive_settlement_clicks(self):
        for in_map, in_combat in ((True, False), (False, True)):
            with self.subTest(in_map=in_map, in_combat=in_combat):
                handler = self.make_handler()
                handler.is_in_map.return_value = in_map
                handler.is_combat_executing.return_value = in_combat
                with patch.object(Camera, '_update_view', return_value=True) as parent:
                    self.assertTrue(handler._update_view())
                parent.assert_called_once_with()
                handler.device.click.assert_not_called()

    def test_unrecognized_screen_keeps_existing_map_failure(self):
        handler = self.make_handler()
        handler.handle_battle_status = Mock(return_value=False)
        handler.handle_auto_search_exp_info = Mock(return_value=False)
        error = MapDetectionError('未知页面')
        with patch.object(Camera, '_update_view', side_effect=error):
            with self.assertRaises(MapDetectionError) as caught:
                handler._update_view()
        self.assertIs(caught.exception, error)
        handler.device.click.assert_not_called()

    def test_recognized_popup_resets_timeout_before_unknown_transition(self):
        handler = self.make_handler()
        clock = VirtualClock()
        state = SimpleNamespace(frame=0)

        def screenshot():
            state.frame += 1
            clock.now += 0.5

        def update_view():
            if 9 <= state.frame <= 20:
                return False
            raise MapDetectionError('未知转场必须仍然超时')

        handler.device.screenshot.side_effect = screenshot
        with patch('module.base.timer.time', clock), patch.object(OSMap, '_update_view', side_effect=update_view):
            with self.assertRaises(MapDetectionError):
                handler.update()
        self.assertGreaterEqual(state.frame, 31)
        self.assertLess(state.frame, 40)

    def test_current_ap_read_confirms_map_before_opening_panel(self):
        handler = self.make_handler()
        steps = []
        handler.update = Mock(side_effect=lambda: steps.append('map'))
        handler.action_point_enter = Mock(side_effect=lambda: steps.append('enter'))
        handler.action_point_safe_get = Mock(side_effect=lambda: steps.append('read'))
        handler.action_point_quit = Mock(side_effect=lambda: steps.append('quit'))
        handler._action_point_current = 17
        self.assertEqual(handler._read_current_action_point(), 17)
        self.assertEqual(steps, ['map', 'enter', 'read', 'quit'])


if __name__ == '__main__':
    unittest.main()
