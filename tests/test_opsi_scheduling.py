import unittest
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from module.campaign.os_run import OSCampaignRun
from module.config.config import TaskEnd
from module.os.tasks.prevent_action_point_overflow import OpsiPreventActionPointOverflow
from module.os.tasks.scheduling import OpsiScheduling
from module.os.tasks.explore import OpsiExplore
from module.os.tasks.hazard_leveling import OpsiHazard1Leveling
from module.os_handler.action_point import ActionPointLimit


class SmartSchedulingConfig:
    """仅提供智能调度与防溢出测试所需的配置接口。"""

    def __init__(self, task_command='OpsiScheduling'):
        self.task = SimpleNamespace(command=task_command)
        self.task_delay_calls = []

    def cross_get(self, keys, default=None):
        if keys == 'OpsiScheduling.Scheduler.ServerUpdate':
            return '00:00'
        return default

    def task_delay(self, *args, **kwargs):
        self.task_delay_calls.append((args, kwargs))

    @staticmethod
    def temporary(**kwargs):
        return nullcontext()

    @staticmethod
    def task_stop():
        raise TaskEnd


class MeowPreserveConfig:
    """提供智能调度代跑短猫时的共享行动力保留状态。"""

    def __init__(self):
        self.OS_ACTION_POINT_PRESERVE = 180

    @contextmanager
    def temporary(self, **kwargs):
        backup = {key: getattr(self, key) for key in kwargs}
        for key, value in kwargs.items():
            setattr(self, key, value)
        try:
            yield
        finally:
            for key, value in backup.items():
                setattr(self, key, value)

    @staticmethod
    def task_stop():
        raise AssertionError('达到短猫保留值不应停止智能调度')


class SchedulingMeowHarness:
    """复现短猫达到自身阈值后异常冒泡的最小调度环境。"""

    TASK_NAME_MEOWFFICER_FARMING = OpsiScheduling.TASK_NAME_MEOWFFICER_FARMING

    def __init__(self):
        self.config = MeowPreserveConfig()
        self.executed_task_name = None

    def run_meowfficer_farming_once(self, ap_preserve):
        self.config.OS_ACTION_POINT_PRESERVE = ap_preserve
        raise ActionPointLimit(total=5985, preserve=ap_preserve)

    def _run_with_opsi_task_context(self, task_name, func, **kwargs):
        self.executed_task_name = task_name
        return func(**kwargs)

    def run_scheduled_meowfficer_farming(self, ap_preserve):
        return OpsiScheduling._run_scheduled_meowfficer_farming(self, ap_preserve)


class SchedulingMeowCostLimitHarness(SchedulingMeowHarness):
    def run_meowfficer_farming_once(self, ap_preserve):
        self.config.OS_ACTION_POINT_PRESERVE = ap_preserve
        raise ActionPointLimit(current=15, total=15, cost=120)


class TestSmartSchedulingMeowPreserve(unittest.TestCase):
    def test_returns_to_scheduling_and_restores_global_preserve_at_meow_limit(self):
        scheduling = SchedulingMeowHarness()

        scheduling.run_scheduled_meowfficer_farming(ap_preserve=6000)

        self.assertEqual(
            scheduling.executed_task_name,
            OpsiScheduling.TASK_NAME_MEOWFFICER_FARMING,
        )
        self.assertEqual(scheduling.config.OS_ACTION_POINT_PRESERVE, 180)

    def test_propagates_real_ap_shortage_and_still_restores_global_preserve(self):
        scheduling = SchedulingMeowCostLimitHarness()

        with self.assertRaises(ActionPointLimit):
            scheduling.run_scheduled_meowfficer_farming(ap_preserve=6000)

        self.assertEqual(scheduling.config.OS_ACTION_POINT_PRESERVE, 180)


class TestSmartSchedulingExploreDelay(unittest.TestCase):
    def test_skips_campaign_initialization_when_opsi_explore_is_in_progress(self):
        runner = OSCampaignRun.__new__(OSCampaignRun)
        runner.config = SmartSchedulingConfig()

        with (
            patch.object(runner, 'is_in_opsi_explore', return_value=True),
            patch.object(runner, '_run_opsi_task_with_ap_overflow_guard') as run_task,
        ):
            with self.assertRaises(TaskEnd):
                runner.opsi_scheduling()

        self.assertEqual(
            runner.config.task_delay_calls,
            [
                (
                    (),
                    {
                        'server_update': '00:00',
                        'task': 'OpsiScheduling',
                    },
                )
            ],
        )
        run_task.assert_not_called()

    def test_initializes_campaign_when_opsi_explore_is_complete(self):
        runner = OSCampaignRun.__new__(OSCampaignRun)
        runner.config = SmartSchedulingConfig()

        with (
            patch.object(runner, 'is_in_opsi_explore', return_value=False),
            patch.object(runner, '_run_opsi_task_with_ap_overflow_guard') as run_task,
        ):
            runner.opsi_scheduling()

        self.assertEqual(runner.config.task_delay_calls, [])
        run_task.assert_called_once()

    def test_delays_scheduling_when_opsi_explore_is_in_progress(self):
        scheduling = OpsiScheduling.__new__(OpsiScheduling)
        scheduling.config = SmartSchedulingConfig()

        with (
            patch.object(scheduling, 'is_in_opsi_explore', return_value=True),
            patch.object(scheduling, 'is_smart_scheduling_enabled') as enabled,
        ):
            with self.assertRaises(TaskEnd):
                scheduling.run_smart_scheduling()

        self.assertEqual(
            scheduling.config.task_delay_calls,
            [
                (
                    (),
                    {
                        'server_update': '00:00',
                        'task': 'OpsiScheduling',
                    },
                )
            ],
        )
        enabled.assert_not_called()

    def test_does_not_delay_when_smart_scheduling_is_normally_disabled(self):
        scheduling = OpsiScheduling.__new__(OpsiScheduling)
        scheduling.config = SmartSchedulingConfig()

        with (
            patch.object(scheduling, 'is_in_opsi_explore', return_value=False),
            patch.object(scheduling, 'is_smart_scheduling_enabled', return_value=False),
        ):
            scheduling.run_smart_scheduling()

        self.assertEqual(scheduling.config.task_delay_calls, [])

    def test_prevent_overflow_delays_itself_during_opsi_explore(self):
        prevent = OpsiPreventActionPointOverflow.__new__(OpsiPreventActionPointOverflow)
        prevent.config = SmartSchedulingConfig(
            task_command='OpsiPreventActionPointOverflow'
        )

        with (
            patch.object(
                prevent,
                '_get_prevent_action_point_overflow_thresholds',
                return_value=(200, 0),
            ),
            patch.object(
                prevent,
                '_get_prevent_action_point_overflow_task',
                return_value='OpsiScheduling',
            ),
            patch.object(
                prevent,
                '_get_current_action_point_for_overflow',
                return_value=200,
            ),
            patch.object(prevent, 'is_in_opsi_explore', return_value=True),
            patch.object(
                prevent,
                '_run_with_opsi_task_context',
                side_effect=lambda task, func, *args, **kwargs: func(*args, **kwargs),
            ),
            patch.object(
                prevent,
                'get_yellow_coins',
                side_effect=AssertionError('开荒期间不应进入智能调度决策'),
            ),
        ):
            with self.assertRaises(TaskEnd):
                prevent.run_prevent_action_point_overflow()

        self.assertEqual(
            prevent.config.task_delay_calls,
            [
                (
                    (),
                    {
                        'server_update': True,
                        'task': 'OpsiPreventActionPointOverflow',
                    },
                )
            ],
        )


class ExploreSchedulingConfig:
    def __init__(self, explore=True, scheduling=True, preserve=True):
        self.values = {
            'OpsiExplore.OpsiExplore.EnableSmartScheduling': explore,
            'OpsiScheduling.Scheduler.Enable': scheduling,
            'OpsiScheduling.OpsiScheduling.UseSmartSchedulingOperationCoinsPreserve': preserve,
            'OpsiScheduling.OpsiScheduling.OperationCoinsPreserve': 30000,
            'OpsiScheduling.OpsiScheduling.OperationCoinsReturnThreshold': 20000,
        }

    def cross_get(self, keys, default=None):
        if keys == 'OpsiScheduling.Storage.Storage':
            return getattr(self, 'storage', default)
        return self.values.get(keys, default)

    def is_task_enabled(self, task):
        return self.values.get(f'{task}.Scheduler.Enable', False)


class TestExploreSchedulingEnable(unittest.TestCase):
    def test_explore_checks_scheduling_threshold_before_loading_zones(self):
        explore = OpsiExplore.__new__(OpsiExplore)
        explore.config = ExploreSchedulingConfig()
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

    def test_requires_all_three_switches(self):
        explore = OpsiExplore.__new__(OpsiExplore)
        for key in ('explore', 'scheduling', 'preserve'):
            values = {'explore': True, 'scheduling': True, 'preserve': True}
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

    def test_cl1_low_coins_returns_to_explore_without_coin_replenish(self):
        scheduling = OpsiScheduling.__new__(OpsiScheduling)
        scheduling.config = ExploreSchedulingConfig()
        scheduling.config.task_delay_calls = []
        scheduling.config.task_call_calls = []
        scheduling.config.task_delay = lambda *args, **kwargs: scheduling.config.task_delay_calls.append((args, kwargs))
        scheduling.config.task_call = lambda *args, **kwargs: scheduling.config.task_call_calls.append((args, kwargs))
        scheduling.config.task_stop = lambda: (_ for _ in ()).throw(TaskEnd)
        with (
            patch.object(scheduling, '_get_explore_scheduling_phase', return_value=scheduling.EXPLORE_SCHEDULING_PHASE_CL1),
            patch.object(scheduling, '_set_explore_scheduling_phase') as set_phase,
            patch.object(scheduling, '_clear_coin_replenish_target') as clear_coin,
            patch.object(scheduling, '_clear_ap_replenish_active') as clear_ap,
        ):
            with self.assertRaises(TaskEnd):
                scheduling._return_to_explore_when_coins_low(29999, 30000)
        set_phase.assert_called_once_with(scheduling.EXPLORE_SCHEDULING_PHASE_EXPLORE)
        clear_coin.assert_called_once()
        clear_ap.assert_called_once()
        self.assertEqual(
            scheduling.config.task_call_calls,
            [(('OpsiExplore',), {'force_call': True})],
        )

    def test_completed_explore_with_low_coins_enters_coin_task(self):
        explore = OpsiExplore.__new__(OpsiExplore)
        explore.config = ExploreSchedulingConfig()
        explore.config.task_call_calls = []
        explore.config.task_call = lambda *args, **kwargs: explore.config.task_call_calls.append((args, kwargs))
        with (
            patch.object(explore, 'get_yellow_coins', return_value=29999),
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

    def test_completed_explore_with_sufficient_coins_does_not_call_scheduling(self):
        explore = OpsiExplore.__new__(OpsiExplore)
        explore.config = ExploreSchedulingConfig()
        explore.config.task_call_calls = []
        explore.config.task_call = lambda *args, **kwargs: explore.config.task_call_calls.append((args, kwargs))
        with (
            patch.object(explore, 'get_yellow_coins', return_value=30000),
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
