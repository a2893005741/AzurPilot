import unittest
from datetime import timedelta
from unittest.mock import Mock

from module.campaign.operation_handover import (
    DELEGATION_BATTLE_MAX,
    DELEGATION_HANDOVER_START,
    DELEGATION_BOOK_MAX,
    DELEGATION_DETAIL_CLAIM,
    DELEGATION_DETAIL_CLOSE,
    DELEGATION_SHIP_SKIP,
    DELEGATION_TOTAL_LEAVE,
    OperationHandover,
)


class TestOperationHandover(unittest.TestCase):
    def make_operation(self):
        operation = object.__new__(OperationHandover)
        operation.device = Mock()
        operation.config = Mock()
        operation.config.OperationHandover_BattleCount = 2
        operation.config.OperationHandover_FullDelegationBookCount = 1
        operation.config.task_delay = Mock()
        operation._handover_finished = False
        operation.appear = Mock(return_value=False)
        operation.handle_popup_confirm = Mock(return_value=False)
        return operation

    def test_idle_starts_configured_batch(self):
        operation = self.make_operation()
        operation._set_handover_amount = Mock(return_value=True)
        operation._read_handover_duration = Mock(return_value=timedelta(minutes=12))
        operation._read_handover_remaining = Mock(return_value=timedelta(minutes=48))
        operation._read_available_books = Mock(return_value=3)

        def visible(button, **kwargs):
            if getattr(operation, '_handover_start_pending', False):
                return button is DELEGATION_DETAIL_CLOSE
            return button is DELEGATION_HANDOVER_START

        operation.appear = Mock(side_effect=visible)

        self.assertTrue(operation.handle_handover_panel())
        operation._set_handover_amount.assert_called_once_with(2, 1)
        operation.device.click.assert_called_once_with(DELEGATION_HANDOVER_START)
        operation.config.task_delay.assert_not_called()

        self.assertTrue(operation.handle_handover_panel())
        operation.device.click.assert_called_with(DELEGATION_DETAIL_CLOSE)
        operation.config.task_delay.assert_called_once()

    def test_running_handover_delays_without_terminating(self):
        operation = self.make_operation()
        operation.appear = Mock(side_effect=lambda button, **kwargs: button is DELEGATION_DETAIL_CLOSE)
        operation._read_handover_remaining = Mock(return_value=timedelta(minutes=7))

        self.assertTrue(operation.handle_handover_panel())
        operation.device.click.assert_called_once_with(DELEGATION_DETAIL_CLOSE)
        operation.config.task_delay.assert_called_once()
        self.assertNotIn(
            DELEGATION_DETAIL_CLOSE.name.replace('_CLOSE', '_TERMINATE'),
            [getattr(item.args[0], 'name', '') for item in operation.device.click.call_args_list],
        )

    def test_completed_handover_claims_and_leaves(self):
        operation = self.make_operation()
        visible = {DELEGATION_DETAIL_CLAIM}
        operation.appear = Mock(side_effect=lambda button, **kwargs: button in visible)

        self.assertTrue(operation.handle_handover_panel())
        operation.device.click.assert_called_once_with(DELEGATION_DETAIL_CLAIM)

        visible.clear()
        visible.add(DELEGATION_TOTAL_LEAVE)
        self.assertTrue(operation.handle_handover_panel())
        operation.device.click.assert_has_calls([
            unittest.mock.call(DELEGATION_DETAIL_CLAIM),
            unittest.mock.call(DELEGATION_TOTAL_LEAVE),
        ])

    def test_unknown_remaining_time_is_fail_closed(self):
        operation = self.make_operation()
        operation.appear = Mock(side_effect=lambda button, **kwargs: button is DELEGATION_DETAIL_CLOSE)
        operation._read_handover_remaining = Mock(return_value=None)

        self.assertTrue(operation.handle_handover_panel())
        operation.device.click.assert_called_once_with(DELEGATION_DETAIL_CLOSE)
        operation.config.task_delay.assert_called_once()

    def test_max_buttons_avoid_repeated_increment_clicks(self):
        operation = self.make_operation()
        operation._read_count = Mock(side_effect=[1, 15, 0, 15])

        self.assertTrue(operation._set_handover_amount(15, 15))
        self.assertEqual(
            [call.args[0] for call in operation.device.click.call_args_list],
            [DELEGATION_BATTLE_MAX, DELEGATION_BOOK_MAX],
        )

    def test_reward_page_waits_one_frame_after_state_probe(self):
        operation = self.make_operation()
        operation.appear = Mock(side_effect=lambda button, **kwargs: button is DELEGATION_SHIP_SKIP)

        self.assertTrue(operation.handle_handover_panel())
        operation.device.click.assert_not_called()

        self.assertTrue(operation.handle_handover_panel())
        operation.device.click.assert_called_once_with(DELEGATION_SHIP_SKIP)

    def test_run_retries_transient_reward_page_detection(self):
        operation = self.make_operation()
        operation.config.Campaign_Name = '1-1'
        operation.config.Campaign_Event = 'campaign_main'
        operation.config.Campaign_Mode = 'normal'
        operation.config.override = Mock()
        operation.handle_stage_name = Mock(return_value=('1-1', 'campaign_main'))
        operation.load_campaign = Mock()
        operation.campaign = Mock()
        operation.stage = '1-1'
        operation.loop = Mock(return_value=iter([None, None]))
        operation.appear = Mock(return_value=False)
        operation._handover_panel_is_open = Mock(return_value=True)
        def handle_once():
            if operation.handle_handover_panel.call_count == 2:
                operation._handover_finished = True
            return operation.handle_handover_panel.call_count == 2

        operation.handle_handover_panel = Mock(side_effect=handle_once)
        operation._handover_finished = True

        operation.run()

        self.assertEqual(operation.handle_handover_panel.call_count, 2)
        operation.config.task_delay.assert_not_called()

    def test_start_requires_running_state_confirmation(self):
        operation = self.make_operation()
        operation._set_handover_amount = Mock(return_value=True)
        operation._read_handover_duration = Mock(return_value=timedelta(minutes=12))
        operation._read_handover_remaining = Mock(return_value=timedelta(minutes=48))
        operation._read_available_books = Mock(return_value=3)

        def visible(button, **kwargs):
            if getattr(operation, '_handover_start_pending', False):
                return button is DELEGATION_DETAIL_CLOSE
            return button is DELEGATION_HANDOVER_START

        operation.appear = Mock(side_effect=visible)
        self.assertTrue(operation.handle_handover_panel())
        self.assertFalse(operation._handover_finished)
        operation.device.click.assert_called_once_with(DELEGATION_HANDOVER_START)
        operation.config.task_delay.assert_not_called()

        self.assertTrue(operation.handle_handover_panel())
        self.assertTrue(operation._handover_finished)
        operation.device.click.assert_has_calls([
            unittest.mock.call(DELEGATION_HANDOVER_START),
            unittest.mock.call(DELEGATION_DETAIL_CLOSE),
        ])
        operation.config.task_delay.assert_called_once()

    def test_duration_is_read_after_amount_configuration(self):
        operation = self.make_operation()
        events = []
        operation.appear = Mock(side_effect=lambda button, **kwargs: button is DELEGATION_HANDOVER_START)
        operation._set_handover_amount = Mock(side_effect=lambda *_: events.append('set') or True)
        operation._read_handover_duration = Mock(
            side_effect=lambda: events.append('duration') or timedelta(minutes=12))
        operation._read_handover_remaining = Mock(
            side_effect=lambda: events.append('remaining') or timedelta(minutes=48))
        operation._read_available_books = Mock(return_value=3)

        self.assertTrue(operation.handle_handover_panel())
        self.assertLess(events.index('set'), events.index('duration'))
        self.assertLess(events.index('set'), events.index('remaining'))

    def test_insufficient_time_does_not_start(self):
        operation = self.make_operation()
        operation.appear = Mock(side_effect=lambda button, **kwargs: button is DELEGATION_HANDOVER_START)
        operation._read_handover_duration = Mock(return_value=timedelta(minutes=12))
        operation._read_handover_remaining = Mock(return_value=timedelta(minutes=5))
        operation._read_available_books = Mock(return_value=3)
        operation._set_handover_amount = Mock(return_value=True)

        self.assertTrue(operation.handle_handover_panel())
        operation._set_handover_amount.assert_called_once_with(2, 1)
        self.assertNotIn(DELEGATION_HANDOVER_START, [item.args[0] for item in operation.device.click.call_args_list])

    def test_insufficient_books_does_not_start(self):
        operation = self.make_operation()
        operation.appear = Mock(side_effect=lambda button, **kwargs: button is DELEGATION_HANDOVER_START)
        operation._read_handover_duration = Mock(return_value=timedelta(minutes=12))
        operation._read_handover_remaining = Mock(return_value=timedelta(minutes=48))
        operation._read_available_books = Mock(return_value=0)
        operation._set_handover_amount = Mock()

        self.assertTrue(operation.handle_handover_panel())
        operation._set_handover_amount.assert_not_called()
        self.assertNotIn(DELEGATION_HANDOVER_START, [item.args[0] for item in operation.device.click.call_args_list])

    def test_run_never_calls_campaign_run(self):
        operation = self.make_operation()
        operation.config.Campaign_Name = '1-1'
        operation.config.Campaign_Event = 'campaign_main'
        operation.config.Campaign_Mode = 'normal'
        operation.config.override = Mock()
        operation.handle_stage_name = Mock(return_value=('1-1', 'campaign_main'))
        operation.load_campaign = Mock()
        operation.campaign = Mock()
        operation.stage = '1-1'
        operation.campaign.ENTRANCE = object()
        operation.loop = Mock(side_effect=[[None], [None]])
        operation.appear = Mock(side_effect=[True])
        operation.handle_handover_panel = Mock(return_value=True)
        operation._handover_finished = True

        operation.run()
        operation.campaign.run.assert_not_called()

    def test_run_reuses_already_open_handover_panel(self):
        operation = self.make_operation()
        operation.config.Campaign_Name = '1-1'
        operation.config.Campaign_Event = 'campaign_main'
        operation.config.Campaign_Mode = 'normal'
        operation.config.override = Mock()
        operation.handle_stage_name = Mock(return_value=('1-1', 'campaign_main'))
        operation.load_campaign = Mock()
        operation.campaign = Mock()
        operation.stage = '1-1'
        operation.loop = Mock(side_effect=[[None]])
        operation.appear = Mock(side_effect=lambda button, **kwargs: button is DELEGATION_DETAIL_CLOSE)
        operation.handle_handover_panel = Mock(return_value=True)
        operation._handover_finished = True

        operation.run()

        operation.campaign.ensure_campaign_ui.assert_not_called()
        operation.device.screenshot.assert_called_once_with()
        operation.handle_handover_panel.assert_called_once_with()

    def test_run_refreshes_after_clicking_handover_entry(self):
        operation = self.make_operation()
        operation.config.Campaign_Name = '1-1'
        operation.config.Campaign_Event = 'campaign_main'
        operation.config.Campaign_Mode = 'normal'
        operation.config.override = Mock()
        operation.handle_stage_name = Mock(return_value=('1-1', 'campaign_main'))
        operation.load_campaign = Mock()
        operation.campaign = Mock()
        operation.stage = '1-1'
        operation.loop = Mock(return_value=iter([None]))
        operation.appear = Mock(side_effect=lambda button, **kwargs: button.name == 'OPERATION_HANDOVER_ENTRY')
        operation.handle_handover_panel = Mock(return_value=True)
        operation._handover_finished = True

        operation.run()

        self.assertEqual(operation.device.screenshot.call_count, 2)
        operation.device.click.assert_called_once()
        self.assertEqual(operation.loop.call_args.kwargs['skip_first'], False)

    def test_run_clicks_ocr_stage_entrance_without_color_detection(self):
        operation = self.make_operation()
        operation.config.Campaign_Name = '1-1'
        operation.config.Campaign_Event = 'campaign_main'
        operation.config.Campaign_Mode = 'normal'
        operation.config.override = Mock()
        operation.handle_stage_name = Mock(return_value=('1-1', 'campaign_main'))
        operation.load_campaign = Mock()
        operation.campaign = Mock()
        operation.stage = '1-1'
        operation.campaign.ENTRANCE = object()
        operation.loop = Mock(side_effect=[[None], [None]])
        operation.handle_handover_panel = Mock(return_value=True)
        operation._handover_finished = True

        calls = []

        def appear(button, **kwargs):
            calls.append((button, kwargs))
            return button is operation.campaign.ENTRANCE

        operation.appear = Mock(side_effect=appear)
        operation.run()

        self.assertNotIn((operation.campaign.ENTRANCE, {}), calls)
        operation.device.click.assert_called_once_with(operation.campaign.ENTRANCE)

    def test_run_accepts_existing_completed_handover_detail(self):
        operation = self.make_operation()
        operation.config.Campaign_Name = '14-4'
        operation.config.Campaign_Event = 'campaign_main'
        operation.config.Campaign_Mode = 'normal'
        operation.config.override = Mock()
        operation.handle_stage_name = Mock(return_value=('14-4', 'campaign_main'))
        operation.load_campaign = Mock()
        operation.campaign = Mock()
        operation.stage = '14-4'
        operation.loop = Mock(side_effect=[[None], [None]])
        operation.handle_handover_panel = Mock(return_value=True)
        operation._handover_finished = True
        operation.appear = Mock(side_effect=lambda button, **kwargs: button is DELEGATION_DETAIL_CLAIM)

        operation.run()

        operation.device.click.assert_not_called()
        operation.handle_handover_panel.assert_called_once_with()



if __name__ == '__main__':
    unittest.main()
