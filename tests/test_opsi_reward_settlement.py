"""回放真实奖励窗口及延迟转场，验证计划作战入口和普通战斗的收尾。"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from module.base.timer import Timer
from module.base.utils import load_image
from module.os_combat.combat import Combat
from module.os_handler.assets import (
    AUTO_SEARCH_REWARD, STRATEGIC_SEARCH_MAP_OPTION_OFF, STRATEGIC_SEARCH_POPUP_CHECK,
)
from module.os_handler.strategic import StrategicSearchHandler
from tests.test_opsi_cl1_speed import VirtualClock


FIXTURES = Path(__file__).parent / 'fixtures' / 'opsi_auto_search'


class TestOpsiRewardSettlement(unittest.TestCase):
    def make_handler(self, cls, fixture='auto_search_reward.png'):
        handler = cls.__new__(cls)
        handler.config = SimpleNamespace(SERVER='cn')
        handler.device = Mock(image=load_image(str(FIXTURES / fixture)))
        handler.interval_timer = {}
        handler.handle_map_event = Mock(return_value=False)
        return handler

    def test_strategic_entry_closes_reward_and_waits_for_popup_confirmation(self):
        handler = self.make_handler(StrategicSearchHandler)
        clock = VirtualClock()
        state = SimpleNamespace(phase='reward', clicked_at=None, screenshots=0)
        frames = {
            'reward': handler.device.image,
            'map': load_image('assets/cn/os_handler/STRATEGIC_SEARCH_MAP_OPTION_OFF.png'),
            'popup': load_image('assets/cn/os_handler/STRATEGIC_SEARCH_POPUP_CHECK.png'),
        }

        def screenshot():
            clock.now += 0.2
            state.screenshots += 1
            if state.screenshots > 30:
                self.fail('奖励窗口未关闭或计划作战面板未打开')
            if state.phase == 'reward' and state.clicked_at is not None \
                    and clock.now - state.clicked_at >= 3.2:
                state.phase = 'map'
            handler.device.image = frames[state.phase]

        def click(button):
            if state.phase == 'reward':
                self.assertIs(button, AUTO_SEARCH_REWARD)
                if state.clicked_at is None:
                    state.clicked_at = clock.now
            else:
                self.assertEqual(state.phase, 'map')
                self.assertIs(button, STRATEGIC_SEARCH_MAP_OPTION_OFF)
                state.phase = 'popup'

        handler.device.screenshot.side_effect = screenshot
        handler.device.click.side_effect = click
        with patch('module.base.timer.time', clock):
            self.assertTrue(handler.strategy_search_enter())
        self.assertEqual(state.phase, 'popup')
        self.assertGreaterEqual(state.screenshots, 17)
        self.assertEqual([c.args[0] for c in handler.device.click.call_args_list],
                         [AUTO_SEARCH_REWARD, AUTO_SEARCH_REWARD, STRATEGIC_SEARCH_MAP_OPTION_OFF])

    def test_combat_execute_and_status_accept_summary_after_game_skips_individual_results(self):
        handler = self.make_handler(Combat, 'auto_search_reward_combat.png')
        clock = VirtualClock()
        state = SimpleNamespace(phase='reward', clicked_at=None, screenshots=0)
        drop = Mock()
        for name in (
            'submarine_call_reset', 'combat_auto_reset', 'combat_manual_reset',
            'handle_combat_automation_confirm', 'handle_combat_defeat', 'handle_story_skip',
            'handle_combat_auto', 'handle_combat_manual', 'handle_submarine_call',
            'handle_popup_confirm', 'handle_urgent_commission', 'handle_guild_popup_cancel',
            'handle_vote_popup', 'handle_mission_popup_ack', 'handle_get_ship',
            'handle_auto_search_exit', 'handle_combat_mis_click', 'handle_in_stage',
        ):
            setattr(handler, name, Mock(return_value=False))
        handler.combat_appear = Mock(return_value=False)
        handler.is_in_map = Mock(side_effect=lambda: state.phase == 'map')

        def screenshot():
            clock.now += 0.2
            state.screenshots += 1
            if state.screenshots > 40:
                self.fail('普通战斗遗漏合计奖励，未能返回地图')
            if state.clicked_at is not None and clock.now - state.clicked_at >= 3.2:
                state.phase = 'map'
                handler.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)

        def click(button):
            self.assertIs(button, AUTO_SEARCH_REWARD)
            if state.clicked_at is None:
                state.clicked_at = clock.now

        handler.device.screenshot.side_effect = screenshot
        handler.device.click.side_effect = click
        with patch('module.base.timer.time', clock):
            handler._os_in_map_confirm_timer = Timer(1.5, count=3)
            handler.combat_execute(drop=drop)
            self.assertEqual(state.phase, 'reward', '点击离开不代表已经返回地图')
            handler.combat_status(drop=drop)
        self.assertEqual(state.phase, 'map')
        self.assertGreaterEqual(clock.now - state.clicked_at, 4.5, '返回地图后仍需完成稳定确认')
        self.assertEqual(handler.device.click.call_count, 2)
        self.assertEqual(drop.handle_add.call_count, 2)

    def test_active_battle_never_receives_reward_clicks(self):
        handler = self.make_handler(Combat)
        handler.is_combat_executing = Mock(return_value=True)
        self.assertFalse(handler.handle_battle_status())
        handler.device.click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
