import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from module.map.map_grids import SelectedGrids
from module.tactical.assets import (
    OCR_SKILL_EXP,
    SKILL_CONFIRM,
    TACTICAL_CLASS_CANCEL,
    TACTICAL_CLASS_START,
)
from module.tactical.tactical_class import (
    SKILL_GRIDS,
    ExpOnBookSelect,
    RewardTacticalClass,
)
from module.ui.assets import BACK_ARROW


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
        handler._try_switch_to_next_skill = Mock(return_value="switched")
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


class TestSkillLevelClassify(unittest.TestCase):
    """技能槽位状态判定：区分「可升级」/「已满级」/「槽位未解锁」。"""

    def test_classifies_upgradable_max_and_locked_slots(self):
        classify = RewardTacticalClass._classify_skill_level

        # 可升级：给出 x/y 进度
        self.assertEqual("upgradable", classify("NEXT:0/100"))
        self.assertEqual("upgradable", classify("NEXT:150/1400"))
        # 已满级：MAX（OCR 常截断为 MA）
        self.assertEqual("max", classify("NEXT:MAX"))
        self.assertEqual("max", classify("NEXT:MA"))
        # 槽位未解锁：空白或破折号占位
        self.assertEqual("locked", classify(""))
        self.assertEqual("locked", classify("———l"))
        self.assertEqual("locked", classify("—l"))

    def test_tolerates_truncated_progress_text(self):
        """网格偏移导致进度残缺时仍须判为可升级。

        代码注释记录的实测样本：`NEXT:/1D]` 实为 `NEXT:0/100`，
        `NEXT:/14[]]` 实为 `NEXT:150/1400`。若要求完整的 `\\d+/\\d+`，
        这些真正可升级的技能会被误判为槽位不可用，训练随之提前结束。
        """
        classify = RewardTacticalClass._classify_skill_level

        self.assertEqual("upgradable", classify("NEXT:/1D]"))
        self.assertEqual("upgradable", classify("NEX T:/ 14[]]"))

    def test_unrecognizable_text_continues_as_upgradable(self):
        """无法辨认的等级文本按可升级继续。

        依据游戏行为：该舰娘已无可升级技能时游戏会自行退出技能升级界面，
        因此界面仍在就说明有技能可练，OCR 读不出只是识别问题。按不可升级
        处理会直接结束训练，正是本次修复要消除的中断。
        """
        classify = RewardTacticalClass._classify_skill_level

        self.assertEqual("upgradable", classify("###"))
        self.assertEqual("upgradable", classify("NEXT:"))
        self.assertEqual("upgradable", classify("NEXT"))
        self.assertEqual("upgradable", classify("%%%%"))


class TestHasUpgradableSkill(unittest.TestCase):
    """升满一个技能后，是否还存在其他可升级技能。"""

    @staticmethod
    def _handler(ocr_result):
        handler = object.__new__(RewardTacticalClass)
        handler.device = Mock(image=object())
        return handler, ocr_result

    def _has_upgradable(self, ocr_result):
        handler, _ = self._handler(ocr_result)
        with patch("module.tactical.tactical_class.ExpOnSkillSelect") as ocr:
            ocr.return_value.ocr.return_value = ocr_result
            return handler.has_upgradable_skill()

    def test_reports_upgradable_when_another_slot_is_not_max(self):
        # 一个技能刚升满，另一个仍可升级 -> 应继续下一轮
        self.assertTrue(self._has_upgradable(["NEXT:MAX", "NEXT:0/100", "———l"]))

    def test_reports_none_when_all_slots_are_max_or_locked(self):
        # 其余槽位为满级或未解锁 -> 无可升级技能，流程结束
        self.assertFalse(self._has_upgradable(["NEXT:MAX", "NEXT:MAX", "———l"]))
        self.assertFalse(self._has_upgradable(["NEXT:MAX", "", ""]))

    def test_locked_slot_is_not_treated_as_upgradable(self):
        # 未解锁槽位既不是满级也不可升级，不能触发继续学习
        self.assertFalse(self._has_upgradable(["NEXT:MAX", "———l", "—l"]))


class TestSkillChooseContinuation(unittest.TestCase):
    """_tactical_skill_choose 的「继续 / 结束」分支。"""

    @staticmethod
    def _handler(selected):
        handler = object.__new__(RewardTacticalClass)
        handler.device = Mock()
        handler.find_not_full_level_skill = Mock(return_value=selected)
        handler._tactical_skill_select = Mock()
        return handler

    def test_continues_next_round_when_upgradable_skill_exists(self):
        skill = SKILL_GRIDS.buttons[1]
        handler = self._handler(skill)

        self.assertTrue(handler._tactical_skill_choose())

        handler._tactical_skill_select.assert_called_once_with(skill)
        handler.device.click.assert_called_once_with(SKILL_CONFIRM)

    def test_stops_without_selecting_when_no_upgradable_skill(self):
        handler = self._handler(None)

        self.assertFalse(handler._tactical_skill_choose())

        handler._tactical_skill_select.assert_not_called()
        handler.device.click.assert_not_called()


class TestSkillConfirmGate(unittest.TestCase):
    """SKILL_CONFIRM 界面的门控：开启自动切换时不得直接退出。"""

    @staticmethod
    def _handler(skill_auto_switch, add_new_student, choose_result=True):
        handler = object.__new__(RewardTacticalClass)
        handler.config = SimpleNamespace(
            Tactical_SkillAutoSwitch=skill_auto_switch,
            AddNewStudent_Enable=add_new_student,
        )
        handler.device = Mock()
        handler.appear = Mock(return_value=True)
        handler.interval_reset = Mock()
        handler._tactical_skill_choose = Mock(return_value=choose_result)
        return handler

    def test_continues_when_only_skill_auto_switch_is_enabled(self):
        # 默认配置：SkillAutoSwitch=True / AddNewStudent=False
        # 此前会走 else 分支置 study_finished=True 并退出
        handler = self._handler(True, False)

        handled, study_finished, pending = handler._handle_tactical_skill_confirm(False)

        self.assertTrue(handled)
        self.assertFalse(study_finished)
        handler._tactical_skill_choose.assert_called_once_with()
        handler.device.click.assert_not_called()

    def test_finishes_when_no_upgradable_skill_left(self):
        handler = self._handler(True, False, choose_result=False)

        handled, study_finished, pending = handler._handle_tactical_skill_confirm(False)

        self.assertTrue(handled)
        self.assertTrue(study_finished)
        handler.device.click.assert_called_once_with(BACK_ARROW)

    def test_closes_page_when_both_switches_disabled(self):
        # 两个开关都关闭时保持原行为：不学习技能，关闭界面
        handler = self._handler(False, False)

        handled, study_finished, pending = handler._handle_tactical_skill_confirm(False)

        self.assertTrue(handled)
        self.assertTrue(study_finished)
        handler._tactical_skill_choose.assert_not_called()
        handler.device.click.assert_called_once_with(BACK_ARROW)


class TestWaitUntilAppear(unittest.TestCase):
    """页面等待必须是持续截图循环，不得在循环内休眠。"""

    @staticmethod
    def _handler(appear_results):
        handler = object.__new__(RewardTacticalClass)
        handler.device = Mock()
        handler.appear = Mock(side_effect=appear_results)
        return handler

    def test_keeps_screenshotting_until_button_appears(self):
        # 页面切换慢：前若干次未出现，之后出现 -> 仍应返回 True
        handler = self._handler([False] * 8 + [True])

        self.assertTrue(
            handler._wait_until_appear(TACTICAL_CLASS_START, offset=(30, 30))
        )

        self.assertEqual(handler.device.screenshot.call_count, 9)

    def test_does_not_sleep_inside_state_loop(self):
        # 状态循环内禁止 sleep()，节流由截图本身承担
        handler = self._handler([False] * 4 + [True])

        handler._wait_until_appear(TACTICAL_CLASS_START, offset=(30, 30))

        handler.device.sleep.assert_not_called()

    def test_returns_false_after_timeout(self):
        handler = self._handler([False] * 200)

        with patch("module.tactical.tactical_class.Timer") as timer_cls:
            timer = timer_cls.return_value.start.return_value
            # 前两次未超时，第三次超时
            timer.reached.side_effect = [False, False, True]
            self.assertFalse(
                handler._wait_until_appear(TACTICAL_CLASS_START, offset=(30, 30))
            )

        self.assertEqual(handler.device.screenshot.call_count, 3)
        handler.device.sleep.assert_not_called()


class TestSwitchFailureFallback(unittest.TestCase):
    """切换失败（界面跳转异常）时降级为普通开课，而不是放弃本轮训练。"""

    @staticmethod
    def _handler(switch_result, max_states):
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
        handler._try_switch_to_next_skill = Mock(return_value=switch_result)
        handler._wait_until_appear = Mock(return_value=True)
        handler.appear = Mock(return_value=False)
        return handler

    def test_starts_class_after_switch_failure(self):
        # 满级判断可能来自误读，切换失败不应放弃本轮 -> 仍要点击开始课程
        handler = self._handler("failed", [True])

        self.assertTrue(handler._tactical_books_choose())

        handler.device.click.assert_any_call(TACTICAL_CLASS_START)
        # 降级后跳过满级检查，不再重复触发切换
        handler._try_switch_to_next_skill.assert_called_once_with()
        self.assertEqual(handler._is_current_skill_max.call_count, 1)

    def test_gives_up_when_cannot_return_to_book_page(self):
        # 降级前必须确认已回到教材选择界面，否则放弃避免误点
        handler = self._handler("failed", [True])
        handler._wait_until_appear = Mock(return_value=False)

        self.assertTrue(handler._tactical_books_choose())

        for recorded in handler.device.click.call_args_list:
            self.assertNotEqual(recorded, call(TACTICAL_CLASS_START))

    def test_does_not_start_class_when_skills_exhausted(self):
        # 确无可升级技能时是正常终态，且已返回战术主页，不得再开课
        handler = self._handler("exhausted", [True])

        self.assertTrue(handler._tactical_books_choose())

        for recorded in handler.device.click.call_args_list:
            self.assertNotEqual(recorded, call(TACTICAL_CLASS_START))


class TestSkillExpInvalidReading(unittest.TestCase):
    """教材加成未剔除导致的畸变读数不得被伪装成满级。"""

    @staticmethod
    def _ocr_value(raw):
        ocr = ExpOnBookSelect(buttons=OCR_SKILL_EXP)
        with patch("module.ocr.ocr.Ocr.ocr", return_value=raw):
            return ocr.ocr(None)

    def test_rejects_current_greater_than_total(self):
        # `NEXT:1900+100/4400` 的绿色加成漏剔除 -> `19001/4400`
        # DigitCounter 的 min() 钳位会得到 4400/4400（伪装成满级）
        self.assertEqual((0, 0, 0), self._ocr_value("19001/4400"))
        self.assertEqual((0, 0, 0), self._ocr_value("35007/5800"))

    def test_keeps_valid_readings(self):
        self.assertEqual((1900, 2500, 4400), self._ocr_value("1900/4400"))
        self.assertEqual((4400, 0, 4400), self._ocr_value("4400/4400"))

    def test_is_current_skill_max_returns_none_on_invalid_reading(self):
        handler = object.__new__(RewardTacticalClass)
        handler.device = Mock(image=object())

        with patch("module.tactical.tactical_class.SKILL_EXP") as skill_exp:
            # 畸变读数已被归一为 (0, 0, 0)
            skill_exp.ocr.return_value = (0, 0, 0)
            self.assertIsNone(handler._is_current_skill_max())

            skill_exp.ocr.return_value = (4400, 0, 4400)
            self.assertIs(True, handler._is_current_skill_max())

            skill_exp.ocr.return_value = (1900, 2500, 4400)
            self.assertIs(False, handler._is_current_skill_max())

    def test_does_not_switch_skill_when_reading_is_invalid(self):
        # 读数无效时不得取消课程，否则未满级技能会停训
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
        handler._is_current_skill_max = Mock(return_value=None)
        handler._try_switch_to_next_skill = Mock(return_value=True)

        self.assertTrue(handler._tactical_books_choose())

        handler._try_switch_to_next_skill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
