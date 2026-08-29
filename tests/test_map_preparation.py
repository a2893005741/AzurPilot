import unittest
from unittest.mock import MagicMock, Mock, call, patch

import numpy as np

from module.map.map_operation import (
    DELEGATION_DETAIL_CLAIM,
    DELEGATION_DETAIL_CLOSE,
    DELEGATION_DETAIL_TERMINATE,
    DELEGATION_POPUP_CANCEL,
    DELEGATION_POPUP_CHECK,
    DELEGATION_SHIP_SKIP,
    DELEGATION_TERMINATE_CONFIRM,
    DELEGATION_TOTAL_CONFIRM,
    DELEGATION_TOTAL_LEAVE,
    MAP_DETAIL_IMMEDIATE_START,
    MAP_PREPARATION,
    MAP_PREPARATION_FALLBACK,
    MAP_PREPARATION_HARD,
    MapOperation,
)


class TestMapPreparation(unittest.TestCase):
    def test_delegation_popup_opens_details_instead_of_canceling(self):
        operation = object.__new__(MapOperation)
        operation.device = Mock()
        operation.appear = Mock(side_effect=lambda button, **kwargs: button in {
            DELEGATION_POPUP_CHECK, DELEGATION_POPUP_CANCEL,
        })

        self.assertTrue(operation.handle_delegation_popup())
        operation.device.click.assert_called_once_with(DELEGATION_POPUP_CHECK)

    def test_delegation_detail_claim_clicks_only_claim_button(self):
        operation = object.__new__(MapOperation)
        operation.device = Mock()
        operation.appear = Mock(side_effect=lambda button, **kwargs: button is DELEGATION_DETAIL_CLAIM)
        operation.handle_popup_confirm = Mock(return_value=False)

        self.assertTrue(operation.handle_delegation_popup())
        operation.device.click.assert_called_once_with(DELEGATION_DETAIL_CLAIM)

    def test_delegation_in_progress_terminates_instead_of_closing_details(self):
        operation = object.__new__(MapOperation)
        operation.device = Mock()
        operation._delegation_detail_open = True
        operation.appear = Mock(side_effect=lambda button, **kwargs: button is DELEGATION_DETAIL_TERMINATE)
        operation.handle_popup_confirm = Mock(return_value=False)

        self.assertTrue(operation.handle_delegation_popup())
        operation.device.click.assert_called_once_with(DELEGATION_DETAIL_TERMINATE)
        self.assertTrue(operation._delegation_reward_flow)
        self.assertFalse(operation._delegation_detail_open)

    def test_delegation_termination_confirmation_clicks_confirm_button(self):
        operation = object.__new__(MapOperation)
        operation.device = Mock()
        operation._delegation_termination_pending = True
        operation._delegation_reward_flow = True
        operation.appear = Mock(side_effect=lambda button, **kwargs: button is DELEGATION_TERMINATE_CONFIRM)
        operation.handle_popup_confirm = Mock(return_value=False)

        self.assertTrue(operation.handle_delegation_popup())
        operation.device.click.assert_called_once_with(DELEGATION_TERMINATE_CONFIRM)
        self.assertFalse(operation._delegation_termination_pending)

    def test_delegation_in_progress_closes_and_delays(self):
        operation = object.__new__(MapOperation)
        operation.device = Mock()
        operation.config = Mock()
        operation.config.task_stop.side_effect = RuntimeError
        operation._delegation_detail_open = True
        operation.appear = Mock(side_effect=lambda button, **kwargs: button is DELEGATION_DETAIL_CLOSE)
        operation.handle_popup_confirm = Mock(return_value=False)

        self.assertRaises(RuntimeError, operation.handle_delegation_popup)
        operation.device.click.assert_called_once_with(DELEGATION_DETAIL_CLOSE)
        operation.config.task_delay.assert_called_once_with(minute=(30, 60))
        operation.config.task_stop.assert_called_once_with('Delegation is still running')

    def test_delegation_reward_flow_skips_ship_then_confirms_total(self):
        operation = object.__new__(MapOperation)
        operation.device = Mock()
        operation.handle_popup_confirm = Mock(return_value=False)
        operation._delegation_reward_flow = True
        visible = {DELEGATION_SHIP_SKIP}
        operation.appear = Mock(side_effect=lambda button, **kwargs: button in visible)

        self.assertTrue(operation.handle_delegation_popup())
        operation.device.click.assert_called_once_with(DELEGATION_SHIP_SKIP)

        visible.clear()
        visible.add(DELEGATION_TOTAL_CONFIRM)
        self.assertTrue(operation.handle_delegation_popup())
        operation.device.click.assert_has_calls([call(DELEGATION_SHIP_SKIP), call(DELEGATION_TOTAL_CONFIRM)])

    def test_delegation_total_leave_returns_to_campaign(self):
        operation = object.__new__(MapOperation)
        operation.device = Mock()
        operation.handle_popup_confirm = Mock(return_value=False)
        operation._delegation_reward_flow = True
        operation.appear = Mock(side_effect=lambda button, **kwargs: button is DELEGATION_TOTAL_LEAVE)

        self.assertTrue(operation.handle_delegation_popup())
        operation.device.click.assert_called_once_with(DELEGATION_TOTAL_LEAVE)

    def test_enter_map_marks_hard_direct_loading_as_auto_search(self):
        operation = object.__new__(MapOperation)
        operation.config = Mock(
            campaign_name='hard',
            DropRecord_CombatRecord=False,
            Campaign_UseAutoSearch=True,
        )
        operation.device = Mock()
        operation.stat = Mock()
        operation.stat.new.return_value = MagicMock()
        operation.map_clear_percentage_timer = Mock()
        operation.map_is_auto_search = False
        operation.appear = Mock(return_value=False)
        operation.is_in_map = Mock(return_value=False)
        operation.handle_map_detail = Mock(return_value=False)
        operation.handle_map_mode_switch = Mock(return_value=False)
        operation.handle_auto_search_continue = Mock(return_value=False)
        operation.handle_retirement = Mock(return_value=False)
        operation.handle_use_data_key = Mock(return_value=False)
        operation.handle_submarine_support_popup = Mock(return_value=False)
        operation.handle_combat_low_emotion = Mock(return_value=False)
        operation.handle_urgent_commission = Mock(return_value=False)
        operation.handle_2x_book_popup = Mock(return_value=False)
        operation.handle_submarine_cost_popup = Mock(return_value=False)
        operation.handle_story_skip = Mock(return_value=False)
        operation.is_auto_search_running = Mock(return_value=False)
        operation.is_combat_loading = Mock(return_value=True)

        self.assertTrue(operation.enter_map(Mock(), mode='hard', skip_first_screenshot=True))

        self.assertTrue(operation.map_is_auto_search)
        operation.is_combat_loading.assert_called_once_with()

    def test_fallback_detects_scaled_immediate_start_button(self):
        operation = object.__new__(MapOperation)
        operation.config = Mock(MAP_HAS_CLEAR_PERCENTAGE=False)
        operation.appear = Mock(side_effect=lambda button, **kwargs: button is MAP_PREPARATION_FALLBACK)

        with patch('module.map.map_operation.server.server', 'cn'):
            self.assertTrue(operation.handle_map_preparation())
        operation.appear.assert_any_call(MAP_PREPARATION, offset=(20, 20))
        operation.appear.assert_any_call(MAP_PREPARATION_FALLBACK, threshold=20)

    def test_hard_preparation_returns_hard_button(self):
        operation = object.__new__(MapOperation)
        operation.config = Mock(MAP_HAS_CLEAR_PERCENTAGE=False)
        operation.appear = Mock(side_effect=lambda button, **kwargs: button is MAP_PREPARATION_HARD)

        self.assertIs(operation.handle_map_preparation(), MAP_PREPARATION_HARD)
        self.assertEqual(operation.appear.call_count, 2)
        operation.appear.assert_has_calls([
            call(MAP_PREPARATION, offset=(20, 20)),
            call(MAP_PREPARATION_HARD, offset=(20, 20)),
        ])

    def test_map_detail_clicks_immediate_start(self):
        operation = object.__new__(MapOperation)
        operation.device = Mock()
        operation.appear = Mock(side_effect=lambda button, **kwargs: button is MAP_DETAIL_IMMEDIATE_START)

        self.assertTrue(operation.handle_map_detail())
        operation.appear.assert_called_once_with(MAP_DETAIL_IMMEDIATE_START, interval=2)
        operation.device.click.assert_called_once_with(MAP_DETAIL_IMMEDIATE_START)

    def test_map_detail_button_matches_target_1280x720_screenshot(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        image[486:550, 908:1110] = MAP_DETAIL_IMMEDIATE_START.color

        self.assertTrue(MAP_DETAIL_IMMEDIATE_START.appear_on(image))


if __name__ == '__main__':
    unittest.main()
