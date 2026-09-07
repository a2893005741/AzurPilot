import unittest
from unittest.mock import Mock

from module.combat.assets import EXP_INFO_S
from module.combat.combat import COMBAT_RESULT_CONFIRM, Combat


class TestCombatExpInfo(unittest.TestCase):
    def test_exp_info_clicks_result_confirm_area(self):
        combat = object.__new__(Combat)
        combat.device = Mock()
        combat.is_combat_executing = Mock(return_value=False)
        combat.appear = Mock(side_effect=lambda button: button is EXP_INFO_S)

        self.assertTrue(combat.handle_exp_info())

        combat.device.click.assert_called_once_with(COMBAT_RESULT_CONFIRM)
        self.assertIsNot(combat.device.click.call_args.args[0], EXP_INFO_S)


if __name__ == '__main__':
    unittest.main()
