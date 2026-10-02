"""fork 开荒闭环（每月开荒 ⇄ 智能调度+）的回归测试。

这些用例原在 test_opsi_scheduling.py 中，2026-09-17 同步上游（f2f71d1dd）时随调度侧
接入一起被覆盖。独立成文件，避免后续同步上游测试文件时再次被吞掉。
"""
import unittest
from contextlib import nullcontext
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from module.config.config import TaskEnd
from module.os.tasks.explore import OpsiExplore
from module.os.tasks.hazard_leveling import OpsiHazard1Leveling
from module.os.tasks.scheduling import OpsiScheduling


class ExploreSchedulingConfig:
    def __init__(
        self,
        explore=True,
        scheduling=True,
        preserve=True,
        enable_explore=True,
    ):
        self.values = {
            'OpsiExplore.OpsiExplore.EnableSmartScheduling': explore,
            'OpsiScheduling.Scheduler.Enable': scheduling,
            'OpsiScheduling.OpsiScheduling.UseSmartSchedulingOperationCoinsPreserve': preserve,
            'OpsiScheduling.OpsiScheduling.OperationCoinsPreserve': 30000,
            'OpsiScheduling.OpsiScheduling.OperationCoinsReturnThreshold': 20000,
            'OpsiScheduling.OpsiScheduling.EnableExplore': enable_explore,
            'OpsiScheduling.OpsiScheduling.EnableStronghold': True,
            'OpsiScheduling.OpsiScheduling.EnableObscure': False,
            'OpsiScheduling.OpsiScheduling.EnableAbyssal': False,
            'OpsiScheduling.OpsiScheduling.EnableMeowfficerFarming': False,
        }
        self.OpsiScheduling_TaskPriority = (
            'OpsiExplore > OpsiStronghold > OpsiObscure > '
            'OpsiAbyssal > OpsiMeowfficerFarming'
        )

    def cross_get(self, keys, default=None):
        if keys == 'OpsiScheduling.Storage.Storage':
            return getattr(self, 'storage', default)
        return self.values.get(keys, default)

    def is_task_enabled(self, task):
        return self.values.get(f'{task}.Scheduler.Enable', False)


class TestExploreSchedulingEnable(unittest.TestCase):
    def test_active_explore_blocks_scheduling_when_closed_loop_is_disabled(self):
        scheduling = OpsiScheduling.__new__(OpsiScheduling)
        scheduling.config = ExploreSchedulingConfig(enable_explore=False)
        scheduling.config.values['OpsiExplore.Scheduler.Enable'] = True
        scheduling.config.values['OpsiExplore.Scheduler.NextRun'] = datetime(2026, 9, 1)

        with (
            patch(
                'module.os_handler.mission.get_os_next_reset',
                return_value=datetime(2026, 10, 1),
            ),
            patch.object(
                scheduling,
                '_get_explore_scheduling_phase',
                return_value=scheduling.EXPLORE_SCHEDULING_PHASE_EXPLORE,
            ),
        ):
            self.assertTrue(scheduling.is_in_opsi_explore())

    def test_monthly_explore_is_selected_by_coin_task_priority(self):
        scheduling = OpsiScheduling.__new__(OpsiScheduling)
        scheduling.config = ExploreSchedulingConfig()

        self.assertEqual(
            scheduling._get_enabled_coin_tasks(),
            ['OpsiExplore', 'OpsiStronghold'],
        )

    def test_monthly_explore_can_be_excluded_from_coin_task_priority(self):
        scheduling = OpsiScheduling.__new__(OpsiScheduling)
        scheduling.config = ExploreSchedulingConfig(enable_explore=False)

        self.assertEqual(
            scheduling._get_enabled_coin_tasks(),
            ['OpsiStronghold'],
        )

    def test_monthly_explore_requires_closed_loop_configuration(self):
        scheduling = OpsiScheduling.__new__(OpsiScheduling)
        scheduling.config = ExploreSchedulingConfig(explore=False)

        self.assertEqual(
            scheduling._get_enabled_coin_tasks(),
            ['OpsiStronghold'],
        )

    def test_selected_monthly_explore_is_handed_to_task_queue(self):
        scheduling = OpsiScheduling.__new__(OpsiScheduling)
        scheduling.config = ExploreSchedulingConfig()
        scheduling.config.task_call_calls = []
        scheduling.config.task_call = (
            lambda *args, **kwargs: scheduling.config.task_call_calls.append(
                (args, kwargs)
            )
        )
        scheduling.config.task_stop = lambda: (_ for _ in ()).throw(TaskEnd)

        with (
            patch.object(
                scheduling,
                '_get_explore_scheduling_phase',
                return_value=scheduling.EXPLORE_SCHEDULING_PHASE_EXPLORE,
            ),
            patch.object(scheduling, '_delay_smart_scheduling_to_server_update'),
        ):
            with self.assertRaises(TaskEnd):
                scheduling._run_scheduled_coin_task_once('OpsiExplore', 200)

        self.assertEqual(
            scheduling.config.task_call_calls,
            [(('OpsiExplore',), {'force_call': True})],
        )

    def test_completed_monthly_explore_falls_through_to_next_coin_task(self):
        scheduling = OpsiScheduling.__new__(OpsiScheduling)
        scheduling.config = ExploreSchedulingConfig()

        with patch.object(
            scheduling,
            '_get_explore_scheduling_phase',
            return_value=scheduling.EXPLORE_SCHEDULING_PHASE_COIN_TASK,
        ):
            self.assertFalse(
                scheduling._run_scheduled_coin_task_once('OpsiExplore', 200)
            )

    def test_monthly_explore_handoff_skips_coin_task_auto_search(self):
        scheduling = OpsiScheduling.__new__(OpsiScheduling)
        scheduling.config = ExploreSchedulingConfig()

        with (
            patch.object(
                scheduling,
                '_get_enabled_coin_tasks',
                return_value=['OpsiExplore'],
            ),
            patch.object(scheduling, 'handle_first_auto_search') as auto_search,
            patch.object(
                scheduling,
                '_run_scheduled_coin_task_once',
                side_effect=TaskEnd,
            ),
        ):
            with self.assertRaises(TaskEnd):
                scheduling._dispatch_coin_task(10000, 1000, 50000, 200)

        auto_search.assert_not_called()

    def test_coin_task_dispatch_skips_initial_auto_search(self):
        scheduling = OpsiScheduling.__new__(OpsiScheduling)
        scheduling.config = ExploreSchedulingConfig()
        scheduling._smart_scheduling_first_auto_search_pending = True

        with (
            patch.object(
                scheduling,
                '_get_enabled_coin_tasks',
                return_value=['OpsiExplore', 'OpsiMeowfficerFarming'],
            ),
            patch.object(scheduling, 'run_first_auto_search') as auto_search,
            patch.object(
                scheduling,
                '_run_scheduled_coin_task_once',
                side_effect=[False, True],
            ),
            patch.object(scheduling, '_notify_coin_task_proxy'),
        ):
            scheduling._dispatch_coin_task(10000, 1000, 50000, 200)

        auto_search.assert_not_called()
        self.assertFalse(scheduling._smart_scheduling_first_auto_search_pending)

    def test_completed_explore_finalizes_before_startup_coin_switch(self):
        explore = OpsiExplore.__new__(OpsiExplore)
        explore.config = ExploreSchedulingConfig()
        explore.config.OS_EXPLORE_FILTER = '1'
        explore.config.OpsiExplore_LastZone = 1
        explore.config.OpsiExplore_ExploreProgress = None
        explore.config.OpsiExplore_SpecialRadar = False
        explore.config.Scheduler_NextRun = None
        # 上游开荒收尾新增了月度补扫状态，夹具按未开始补扫提供。
        explore.config.OpsiExplore_MeowfficerCleanupState = None
        explore.config.task_delay = lambda *args, **kwargs: None
        explore.config.task_call = lambda *args, **kwargs: None
        explore.config.multi_set = lambda: nullcontext()
        explore.config.task_stop = lambda: (_ for _ in ()).throw(TaskEnd)
        explore.name_to_zone = lambda zone: SimpleNamespace(zone_id=int(zone))
        with (
            patch.object(explore, '_switch_to_smart_scheduling_after_zone') as switch,
            patch.object(explore, '_finish_explore_scheduling'),
            patch('module.os.tasks.explore.get_os_next_reset'),
        ):
            with self.assertRaises(TaskEnd):
                explore._os_explore()
        switch.assert_not_called()

    def test_skips_initial_auto_search_when_coin_threshold_is_reached(self):
        explore = OpsiExplore.__new__(OpsiExplore)
        explore.config = ExploreSchedulingConfig()
        explore.config.task = SimpleNamespace(command='OpsiExplore')
        with (
            patch.object(explore, '_get_explore_scheduling_phase', return_value=explore.EXPLORE_SCHEDULING_PHASE_EXPLORE),
            patch.object(explore, 'get_yellow_coins', return_value=50000),
            patch.object(explore, '_get_explore_action_point_total', return_value=201),
        ):
            self.assertTrue(explore._should_skip_first_auto_search())

    def test_explore_checks_scheduling_threshold_before_loading_zones(self):
        explore = OpsiExplore.__new__(OpsiExplore)
        explore.config = ExploreSchedulingConfig()
        explore.config.OS_EXPLORE_FILTER = '1'
        explore.config.OpsiExplore_LastZone = 0
        with patch.object(
            explore,
            '_switch_to_smart_scheduling_after_zone',
            side_effect=TaskEnd,
        ):
            with self.assertRaises(TaskEnd):
                explore._os_explore()

    def test_explore_task_stops_when_phase_is_not_explore(self):
        explore = OpsiExplore.__new__(OpsiExplore)
        explore.config = ExploreSchedulingConfig()
        explore.config.task_delay = lambda *args, **kwargs: None
        explore.config.task_stop = lambda: (_ for _ in ()).throw(TaskEnd)
        with patch.object(
            explore,
            '_get_explore_scheduling_phase',
            return_value=explore.EXPLORE_SCHEDULING_PHASE_CL1,
        ):
            with self.assertRaises(TaskEnd):
                explore._delay_explore_for_scheduling_phase()

    def test_enable_switch_accepts_legacy_checkbox_list_value(self):
        explore = OpsiExplore.__new__(OpsiExplore)
        explore.config = ExploreSchedulingConfig()
        explore.config.values[
            'OpsiExplore.OpsiExplore.EnableSmartScheduling'
        ] = [True]
        self.assertTrue(explore._is_explore_scheduling_enabled())

    def test_uses_shared_smart_scheduling_storage_path(self):
        self.assertEqual(
            OpsiExplore.EXPLORE_SCHEDULING_STATE_PATH,
            OpsiScheduling.CONFIG_PATH_SMART_STATE,
        )

    def test_requires_all_four_closed_loop_switches(self):
        explore = OpsiExplore.__new__(OpsiExplore)
        for key in ('explore', 'scheduling', 'preserve', 'enable_explore'):
            values = {
                'explore': True,
                'scheduling': True,
                'preserve': True,
                'enable_explore': True,
            }
            values[key] = False
            explore.config = ExploreSchedulingConfig(**values)
            self.assertFalse(explore._is_explore_scheduling_enabled())

        explore.config = ExploreSchedulingConfig()
        self.assertTrue(explore._is_explore_scheduling_enabled())

    def test_switches_to_cl1_only_at_upper_coin_bound_and_sufficient_ap(self):
        explore = OpsiExplore.__new__(OpsiExplore)
        explore.config = ExploreSchedulingConfig()
        explore.config.task_delay_calls = []
        explore.config.task_call_calls = []
        explore.config.task_delay = lambda *args, **kwargs: explore.config.task_delay_calls.append((args, kwargs))
        explore.config.task_call = lambda *args, **kwargs: explore.config.task_call_calls.append((args, kwargs))
        explore.config.task_stop = lambda: (_ for _ in ()).throw(TaskEnd)
        with (
            patch.object(explore, '_get_explore_scheduling_phase', return_value=explore.EXPLORE_SCHEDULING_PHASE_EXPLORE),
            patch.object(explore, 'get_yellow_coins', return_value=49999),
        ):
            self.assertFalse(explore._switch_to_smart_scheduling_after_zone())
        with (
            patch.object(explore, '_get_explore_scheduling_phase', return_value=explore.EXPLORE_SCHEDULING_PHASE_EXPLORE),
            patch.object(explore, 'get_yellow_coins', return_value=50000),
            patch.object(explore, '_get_explore_action_point_total', return_value=201),
            patch.object(explore, '_set_explore_scheduling_phase') as set_phase,
            patch('module.os.tasks.explore.get_os_next_reset', return_value=object()),
        ):
            with self.assertRaises(TaskEnd):
                explore._switch_to_smart_scheduling_after_zone()
        set_phase.assert_called_once_with(explore.EXPLORE_SCHEDULING_PHASE_CL1)
        self.assertEqual(
            explore.config.task_call_calls,
            [(('OpsiScheduling',), {'force_call': True})],
        )

    def test_cl1_low_coins_returns_to_managed_priority_without_direct_call(self):
        scheduling = OpsiScheduling.__new__(OpsiScheduling)
        scheduling.config = ExploreSchedulingConfig()
        scheduling.config.task_delay_calls = []
        scheduling.config.task_call_calls = []
        scheduling.config.task_delay = lambda *args, **kwargs: scheduling.config.task_delay_calls.append((args, kwargs))
        scheduling.config.task_call = lambda *args, **kwargs: scheduling.config.task_call_calls.append((args, kwargs))
        with (
            patch.object(scheduling, '_get_explore_scheduling_phase', return_value=scheduling.EXPLORE_SCHEDULING_PHASE_CL1),
            patch.object(scheduling, '_set_explore_scheduling_phase') as set_phase,
            patch.object(scheduling, '_clear_coin_replenish_target') as clear_coin,
            patch.object(scheduling, '_clear_ap_replenish_active') as clear_ap,
        ):
            switched = scheduling._return_to_explore_when_coins_low(29999, 30000)
        self.assertTrue(switched)
        set_phase.assert_called_once_with(scheduling.EXPLORE_SCHEDULING_PHASE_EXPLORE)
        clear_coin.assert_called_once()
        clear_ap.assert_called_once()
        self.assertEqual(scheduling.config.task_call_calls, [])

    def test_explore_phase_below_upper_bound_uses_coin_task_priority(self):
        scheduling = OpsiScheduling.__new__(OpsiScheduling)
        scheduling.config = ExploreSchedulingConfig()
        scheduling.config.modified = {}
        scheduling.config.save = lambda: None

        with (
            patch.object(scheduling, 'get_yellow_coins', return_value=49999),
            patch.object(
                scheduling,
                '_get_explore_scheduling_phase',
                return_value=scheduling.EXPLORE_SCHEDULING_PHASE_EXPLORE,
            ),
            patch.object(scheduling, '_get_scheduling_action_point', return_value=(1200, 500)),
            patch.object(scheduling, '_dispatch_coin_task') as dispatch,
            patch.object(scheduling, '_execute_hazard1_leveling') as hazard,
        ):
            scheduling.run_smart_scheduling_once()

        dispatch.assert_called_once()
        hazard.assert_not_called()

    def test_completed_explore_below_coin_target_enters_coin_task(self):
        explore = OpsiExplore.__new__(OpsiExplore)
        explore.config = ExploreSchedulingConfig()
        explore.config.task_call_calls = []
        explore.config.task_call = lambda *args, **kwargs: explore.config.task_call_calls.append((args, kwargs))
        with (
            patch.object(explore, 'get_yellow_coins', return_value=49999),
            patch.object(explore, '_set_explore_scheduling_phase') as set_phase,
        ):
            explore._finish_explore_scheduling()
        set_phase.assert_called_once_with(explore.EXPLORE_SCHEDULING_PHASE_COIN_TASK)
        self.assertEqual(
            explore.config.task_call_calls,
            [(('OpsiScheduling',), {'force_call': True})],
        )

    def test_new_month_resets_stale_phase(self):
        explore = OpsiExplore.__new__(OpsiExplore)
        explore.config = ExploreSchedulingConfig()
        explore.config.storage = {
            explore.EXPLORE_SCHEDULING_MONTH_KEY: 'old',
            explore.EXPLORE_SCHEDULING_PHASE_KEY: explore.EXPLORE_SCHEDULING_PHASE_CL1,
        }
        with patch('module.os.map.get_os_next_reset') as next_reset:
            next_reset.return_value = __import__('datetime').datetime(2026, 9, 1, 3)
            self.assertEqual(
                explore._get_explore_scheduling_phase(),
                explore.EXPLORE_SCHEDULING_PHASE_EXPLORE,
            )

    def test_completed_explore_at_coin_target_does_not_call_scheduling(self):
        explore = OpsiExplore.__new__(OpsiExplore)
        explore.config = ExploreSchedulingConfig()
        explore.config.task_call_calls = []
        explore.config.task_call = lambda *args, **kwargs: explore.config.task_call_calls.append((args, kwargs))
        with (
            patch.object(explore, 'get_yellow_coins', return_value=50000),
            patch.object(explore, '_set_explore_scheduling_phase') as set_phase,
        ):
            explore._finish_explore_scheduling()
        set_phase.assert_called_once_with(explore.EXPLORE_SCHEDULING_PHASE_COMPLETED)
        self.assertEqual(explore.config.task_call_calls, [])

    def test_independent_hazard1_yields_during_closed_loop_cl1(self):
        hazard = OpsiHazard1Leveling.__new__(OpsiHazard1Leveling)
        hazard.config = ExploreSchedulingConfig()
        hazard.config.task_delay = lambda *args, **kwargs: None
        hazard.config.task_stop = lambda: (_ for _ in ()).throw(TaskEnd)
        with (
            patch.object(hazard, '_is_explore_scheduling_enabled', return_value=True),
            patch.object(hazard, '_get_explore_scheduling_phase', return_value=hazard.EXPLORE_SCHEDULING_PHASE_CL1),
        ):
            with self.assertRaises(TaskEnd):
                hazard.run_hazard1_leveling_once()
