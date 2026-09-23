import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from module.os_ash.ash import OSAsh
from module.os_ash.assets import BEACON_LIST, BEACON_REWARD, HELP_ENTER
from module.os_ash.meta import MetaState, OpsiAshBeacon


class TestAshCollectStatus(unittest.TestCase):
    def _status(self, collected, daily):
        ash = object.__new__(OSAsh)
        ash._ash_fully_collected = False
        ash.device = SimpleNamespace(image=object())
        ash.image_color_count = MagicMock(return_value=True)

        collected_ocr = MagicMock()
        collected_ocr.ocr.return_value = (collected, None, None)
        daily_ocr = MagicMock()
        daily_ocr.ocr.return_value = (daily, None, None)
        with patch('module.os_ash.ash.DigitCounter', return_value=collected_ocr), \
                patch('module.os_ash.ash.DailyDigitCounter', return_value=daily_ocr):
            result = ash.ash_collect_status()
        return ash, result

    def test_holding_cap_does_not_mark_daily_collection_complete(self):
        ash, result = self._status(collected=200, daily=100)

        self.assertEqual(result, 200)
        self.assertFalse(ash._ash_fully_collected)

    def test_daily_cap_marks_collection_complete(self):
        ash, result = self._status(collected=100, daily=200)

        self.assertEqual(result, 100)
        self.assertTrue(ash._ash_fully_collected)

    def test_daily_cap_does_not_block_next_beacon_trigger(self):
        ash = object.__new__(OSAsh)
        task_call = MagicMock()
        ash.config = SimpleNamespace(
            is_task_enabled=MagicMock(return_value=True),
            cross_get=MagicMock(return_value=datetime(2026, 9, 25)),
            task_call=task_call,
        )
        ash.ash_collect_status = MagicMock(return_value=100)

        with patch('module.os_ash.ash.current_time', return_value=datetime(2026, 9, 24)):
            self.assertTrue(ash.handle_ash_beacon_attack())

        task_call.assert_called_once_with(task='OpsiAshBeacon')


class TestMetaBeaconState(unittest.TestCase):
    def _meta(self, *, reward=False, attacking=False):
        meta = object.__new__(OpsiAshBeacon)
        meta.appear = MagicMock(
            side_effect=lambda button, **kwargs: (
                button is BEACON_LIST
                or (button is BEACON_REWARD and reward)
                or (button is HELP_ENTER and attacking)
            )
        )
        return meta

    def test_reward_page_wins_over_attacking_marker(self):
        meta = self._meta(reward=True, attacking=True)

        self.assertEqual(meta._get_state(), MetaState.COMPLETE)

    def test_multiple_attacks_count_as_one_beacon_completion(self):
        meta = self._meta()
        meta.device = SimpleNamespace(screenshot=MagicMock())
        meta.config = SimpleNamespace(
            OpsiAshBeacon_AttackMode='current',
            check_task_switch=MagicMock(),
        )
        meta.handle_map_event = MagicMock(return_value=False)
        meta._get_state = MagicMock(
            side_effect=[
                MetaState.ATTACKING,
                MetaState.ATTACKING,
                MetaState.COMPLETE,
                MetaState.INIT,
            ]
        )
        meta._pre_attack = MagicMock(return_value=True)
        meta._satisfy_attack_condition = MagicMock(return_value=True)
        meta._make_an_attack = MagicMock()
        meta._handle_ash_beacon_reward = MagicMock()
        meta._begin_meta = MagicMock(return_value=False)
        meta._meta_receive = []
        meta._meta_category = 'undefined'

        meta._attack_meta()

        self.assertEqual(meta._make_an_attack.call_count, 2)
        meta._handle_ash_beacon_reward.assert_called_once()
        self.assertEqual(meta._meta_receive, ['beacon'])


if __name__ == '__main__':
    unittest.main()
