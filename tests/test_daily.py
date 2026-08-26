import unittest
from unittest.mock import Mock, call, patch

import numpy as np

from module.daily.assets import DAILY_ENTER, DAILY_LOCKED, DAILY_NEXT
from module.daily.daily import Daily
from module.exception import GameStuckError
from module.handler.assets import GUILD_POPUP_CANCEL, GUILD_POPUP_CONFIRM


class AccessTimer:
    """测试用计时器，仅按访问次数推进。"""

    def __init__(self, limit, count=0):
        self.count = count
        self.access = 0

    def start(self):
        self.access = 0
        return self

    def reset(self):
        self.access = 0
        return self

    def reached(self):
        self.access += 1
        return self.access > self.count


class TestDailyCardSwitch(unittest.TestCase):
    @staticmethod
    def _daily_with_frames(frames):
        daily = object.__new__(Daily)
        daily.daily_current = 1
        daily.device = Mock()
        daily.device.image = frames[0]
        remaining = iter(frames[1:])
        daily.handle_daily_additional = Mock(return_value=False)
        daily._daily_switch = None

        def screenshot():
            daily.device.image = next(remaining)
            return daily.device.image

        daily.device.screenshot.side_effect = screenshot
        return daily

    @staticmethod
    def _drive_switch(daily):
        while daily._daily_switch is not None:
            daily.device.screenshot()
            daily._daily_switch_complete()

    def test_next_waits_for_card_to_change_and_stabilize(self):
        old = np.zeros((720, 1280, 3), dtype=np.uint8)
        transition = old.copy()
        transition[118:645, 534:744] = 40
        selected = old.copy()
        selected[118:645, 534:744] = 100
        frames = [old, old, transition, selected, selected, selected, selected, selected]
        daily = self._daily_with_frames(frames)

        with patch('module.daily.daily.Timer', AccessTimer):
            daily.next()
            self._drive_switch(daily)

        self.assertEqual(2, daily.daily_current)
        self.assertEqual(6, daily.device.screenshot.call_count)
        self.assertEqual(call.click(DAILY_NEXT), daily.device.mock_calls[0])
        self.assertTrue(np.array_equal(selected, daily.device.image))

    def test_next_ignores_animated_card_effects_when_waiting_for_stability(self):
        old = np.zeros((720, 1280, 3), dtype=np.uint8)
        transition = old.copy()
        transition[118:645, 534:744] = 40
        selected_a = old.copy()
        selected_a[118:645, 534:744] = 100
        selected_b = selected_a.copy()
        checker = np.indices((527, 210)).sum(axis=0) % 2
        selected_a[118:645, 534:744] += (checker * 20).astype(np.uint8)[..., None]
        selected_b[118:645, 534:744] += ((1 - checker) * 20).astype(np.uint8)[..., None]
        daily = self._daily_with_frames(
            [old, transition, selected_a, selected_b, selected_a, selected_b, selected_a, selected_b]
        )

        with patch('module.daily.daily.Timer', AccessTimer):
            daily.next()
            self._drive_switch(daily)

        self.assertIsNone(daily._daily_switch)
        self.assertTrue(np.array_equal(selected_a, daily.device.image)
                        or np.array_equal(selected_b, daily.device.image))

    def test_next_accepts_changed_card_with_continuous_animation(self):
        old = np.zeros((720, 1280, 3), dtype=np.uint8)
        selected_a = old.copy()
        selected_b = old.copy()
        selected_a[118:645, 534:744] = 80
        selected_b[118:645, 534:744] = 140
        animated_frames = [selected_a, selected_b] * 8
        daily = self._daily_with_frames([old] + animated_frames)

        with patch('module.daily.daily.Timer', AccessTimer):
            daily.next()
            self._drive_switch(daily)

        self.assertIsNone(daily._daily_switch)
        self.assertLess(daily.device.screenshot.call_count, len(animated_frames))

    def test_next_does_not_accept_transient_frame_as_card_change(self):
        old = np.zeros((720, 1280, 3), dtype=np.uint8)
        transient = old.copy()
        transient[118:645, 534:744] = 100
        daily = self._daily_with_frames([old, transient, old] + [old] * 10)

        with patch('module.daily.daily.Timer', AccessTimer):
            daily.next()
            daily.device.screenshot()
            self.assertFalse(daily._daily_switch_complete())
            self.assertTrue(daily._daily_switch['changed'])
            daily.device.screenshot()
            self.assertFalse(daily._daily_switch_complete())
            self.assertFalse(daily._daily_switch['changed'])
            with self.assertRaisesRegex(GameStuckError, '卡片切换等待超时'):
                self._drive_switch(daily)

    def test_next_ignores_old_card_animation_before_switch(self):
        old_a = np.zeros((720, 1280, 3), dtype=np.uint8)
        old_b = old_a.copy()
        checker = np.indices((527, 210)).sum(axis=0) % 2
        old_a[118:645, 534:744] = (checker * 20).astype(np.uint8)[..., None]
        old_b[118:645, 534:744] = ((1 - checker) * 20).astype(np.uint8)[..., None]
        selected = np.zeros((720, 1280, 3), dtype=np.uint8)
        selected[118:645, 534:744] = 100
        daily = self._daily_with_frames([old_a, old_b] + [selected] * 6)

        with patch('module.daily.daily.Timer', AccessTimer):
            daily.next()
            daily.device.screenshot()
            self.assertFalse(daily._daily_switch_complete())
            self.assertFalse(daily._daily_switch['changed'])
            self._drive_switch(daily)

        self.assertIsNone(daily._daily_switch)
        self.assertTrue(np.array_equal(selected, daily.device.image))

    def test_next_does_not_accept_unchanged_previous_card(self):
        old = np.zeros((720, 1280, 3), dtype=np.uint8)
        daily = self._daily_with_frames([old] * 12)

        with patch('module.daily.daily.Timer', AccessTimer):
            with self.assertRaisesRegex(GameStuckError, '卡片切换等待超时'):
                daily.next()
                self._drive_switch(daily)

        self.assertEqual(11, daily.device.screenshot.call_count)

    def test_next_ignores_popup_frame_until_card_really_changes(self):
        old = np.zeros((720, 1280, 3), dtype=np.uint8)
        popup = old.copy()
        popup[200:500, 400:880] = 80
        selected = old.copy()
        selected[118:645, 534:744] = 100
        daily = self._daily_with_frames([old, popup, popup, popup] + [selected] * 12)
        daily.handle_daily_additional.side_effect = [True, True, True] + [False] * 20

        with patch('module.daily.daily.Timer', AccessTimer):
            daily.next()
            for _ in range(3):
                daily.device.screenshot()
                self.assertFalse(daily._daily_switch_complete())
                self.assertFalse(daily._daily_switch['changed'])
            self._drive_switch(daily)

        self.assertGreaterEqual(daily.handle_daily_additional.call_count, 3)
        self.assertTrue(np.array_equal(selected, daily.device.image))

    def test_daily_additional_stays_pending_while_popup_is_visible(self):
        daily = object.__new__(Daily)
        daily.handle_guild_popup_cancel = Mock(return_value=False)
        daily.appear = Mock(return_value=True)

        self.assertTrue(daily.handle_daily_additional())
        daily.appear.assert_has_calls([
            call(GUILD_POPUP_CONFIRM, offset=daily._popup_offset),
            call(GUILD_POPUP_CANCEL, offset=daily._popup_offset),
        ])

    def test_next_past_last_card_does_not_click_or_wait(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        daily = self._daily_with_frames([image])
        daily.daily_current = 7

        daily.next()

        self.assertEqual(8, daily.daily_current)
        daily.device.click.assert_not_called()
        daily.device.screenshot.assert_not_called()


class TestDailyLockedCard(unittest.TestCase):
    def test_locked_card_is_skipped_before_reading_stage_or_entering(self):
        daily = object.__new__(Daily)
        daily.daily_current = 1
        daily.daily_checked = [0, 1, 2, 3, 4, 5, 6]
        daily.device = Mock()
        daily.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)
        daily.emergency_module_development = False

        daily.ui_ensure = Mock()
        daily.next = Mock(side_effect=lambda: setattr(daily, 'daily_current', daily.daily_current + 1))
        daily.is_active = Mock(side_effect=AssertionError('锁定卡片不应读取活跃状态'))
        daily.get_daily_stage_and_fleet = Mock(side_effect=AssertionError('锁定卡片不应读取关卡'))
        daily.daily_execute = Mock(side_effect=AssertionError('锁定卡片不应进入每日任务'))
        daily.appear = Mock(side_effect=lambda button, **kwargs: button is DAILY_LOCKED)

        with patch('module.daily.daily.ENTRANCE_EMERGENCY_MODULE_DEVELOPMENT', object()):
            daily.daily_run_one()

        daily.appear.assert_any_call(DAILY_LOCKED, offset=(30, 30))
        self.assertEqual(7, daily.next.call_count)
        self.assertEqual([0, 1, 2, 3, 4, 5, 6, 7], daily.daily_checked)

    def test_non_contiguous_checked_cards_process_lowest_unchecked_card(self):
        daily = object.__new__(Daily)
        daily.daily_checked = [0, 2]
        daily.device = Mock()
        daily.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)
        daily.ui_ensure = Mock()
        daily.ui_goto = Mock()
        daily.appear = Mock(return_value=False)
        daily.get_daily_stage_and_fleet = Mock(return_value=(1, 1))
        daily.is_active = Mock(return_value=True)
        daily.daily_execute = Mock()

        with patch('module.daily.daily.OCR_REMAIN.ocr', return_value=1):
            daily.daily_run_one()

        daily.daily_execute.assert_called_once_with(remain=1, stage=1, fleet=1)
        self.assertEqual([0, 2, 1], daily.daily_checked)

    def test_daily_run_continues_after_one_card_until_all_cards_checked(self):
        daily = object.__new__(Daily)
        daily.emergency_module_development = False
        daily.config = Mock()

        def run_one():
            if daily.daily_checked == [0]:
                daily.daily_checked.append(7)
                return
            daily.daily_checked.append(next(
                index for index in range(1, 8) if index not in daily.daily_checked
            ))

        daily.daily_run_one = Mock(side_effect=run_one)

        daily.daily_run()

        self.assertEqual(7, daily.daily_run_one.call_count)
        self.assertEqual(set(range(8)), set(daily.daily_checked))


if __name__ == '__main__':
    unittest.main()
