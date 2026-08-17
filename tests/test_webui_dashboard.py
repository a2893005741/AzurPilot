import unittest
from types import SimpleNamespace

from module.webui.app_dashboard import DashboardMixin


class TestDashboardMixin(unittest.TestCase):
    def test_empty_dashboard_groups_do_not_break_overview(self):
        dashboard = DashboardMixin.__new__(DashboardMixin)
        dashboard.__dict__['_log'] = SimpleNamespace(
            dashboard_arg_group=None,
            first_display=True,
        )

        dashboard._update_dashboard()

        self.assertFalse(dashboard._log.first_display)


if __name__ == '__main__':
    unittest.main()
