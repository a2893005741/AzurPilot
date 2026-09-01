import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from module.map.map_grids import SelectedGrids
from module.tactical.assets import TACTICAL_CLASS_CANCEL
from module.tactical.tactical_class import SKILL_GRIDS, RewardTacticalClass


class TestTacticalSkillAutoSwitch(unittest.TestCase):
    @staticmethod
    def _handler(max_states):
        handler = object.__new__(RewardTacticalClass)
        handler.config = SimpleNamespace(
            Tactical_SkillAutoSwitch=True,
            Tactical_TacticalFilter="first",
        )
        handler.device = Mock()
        handler.books = SelectedGrids(
            [
                SimpleNamespace(
                    same_str="unknown",
                    genre_str="Red",
                    tier_str="T1",
                    exp_value=100,
                )
            ]
        )
        handler._tactical_books_get = Mock(return_value=True)
        handler._tactical_book_select = Mock()
        handler._tactical_books_filter_exp = Mock()
        handler._is_current_skill_max = Mock(side_effect=max_states)
        handler._try_switch_to_next_skill = Mock(return_value=True)
        return handler

    def test_switches_before_book_fallback_when_current_skill_is_max(self):
        handler = self._handler([True, False])

        self.assertTrue(handler._tactical_books_choose())

        handler._try_switch_to_next_skill.assert_called_once_with()
        handler.device.click.assert_called_once()

    def test_does_not_cancel_again_when_switch_returns_to_tactical_page(self):
        handler = self._handler([True])
        handler._try_switch_to_next_skill = RewardTacticalClass._try_switch_to_next_skill.__get__(
            handler, RewardTacticalClass
        )
        handler._wait_until_appear = Mock(return_value=True)
        handler.find_not_full_level_skill = Mock(return_value=None)
        handler._return_to_tactical_page = Mock()
        handler.appear = Mock(return_value=False)

        self.assertTrue(handler._tactical_books_choose())

        self.assertEqual(
            handler.device.click.call_args_list,
            [call(TACTICAL_CLASS_CANCEL)],
        )
        handler.device.screenshot.assert_called_once_with()

    def test_keeps_book_selection_for_non_max_skill(self):
        handler = self._handler([False])

        self.assertTrue(handler._tactical_books_choose())

        handler._try_switch_to_next_skill.assert_not_called()
        self.assertEqual(handler._tactical_book_select.call_count, 2)
        handler._tactical_book_select.assert_called_with(handler.books[0])

    def test_finds_unmaxed_skill_after_maxed_skill(self):
        handler = object.__new__(RewardTacticalClass)
        handler.device = Mock(image=object())

        with patch("module.tactical.tactical_class.ExpOnSkillSelect") as ocr:
            ocr.return_value.ocr.return_value = [
                "NEXT:MAX",
                "NEXT:0/100",
                "NEXT:MAX",
            ]
            selected = handler.find_not_full_level_skill()

        self.assertIs(selected, SKILL_GRIDS.buttons[1])


if __name__ == "__main__":
    unittest.main()
