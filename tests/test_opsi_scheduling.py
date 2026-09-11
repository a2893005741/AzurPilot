import unittest
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.campaign.os_run import OSCampaignRun
from module.config.config import Function, TaskEnd
from module.os.operation_siren import OperationSiren
from module.os.tasks.prevent_action_point_overflow import OpsiPreventActionPointOverflow
from module.os.tasks.scheduling import OpsiScheduling
from module.os.tasks.explore import OpsiExplore
from module.os.tasks.hazard_leveling import OpsiHazard1Leveling
from module.os_handler.action_point import ActionPointLimit
from module.os_handler.os_status import OSStatus


class TestOpsiTaskCooldown(unittest.TestCase):
    """到期任务不能被当成冷却任务，防止代理任务反复写回过去的运行时间。"""

    def setUp(self):
        self.now = datetime(2026, 9, 8, 7, 18, 17)
        self.update = datetime(2026, 9, 9)
        self.status = OSStatus.__new__(OSStatus)
        self.status.config = SimpleNamespace(pending_task=[], waiting_task=[])
        for name, value in (
            ('current_time', self.now),
            ('get_server_next_update', self.update),
        ):
            patcher = patch(f'module.os_handler.os_status.{name}', return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def make_task(next_run, command='OpsiDaily', enabled=True):
        return Function({'Scheduler': {
            'Command': command,
            'Enable': enabled,
            'NextRun': next_run,
        }})

    def test_expired_or_due_tasks_are_not_cooling_down(self):
        for next_run in (datetime(2026, 9, 7), self.now - timedelta(seconds=1), self.now):
            # 队列是较早生成的快照，等待队列里的任务也可能已经到期。
            for queue in ('pending_task', 'waiting_task'):
                with self.subTest(next_run=next_run, queue=queue):
                    self.status.config.pending_task = []
                    self.status.config.waiting_task = []
                    setattr(self.status.config, queue, [self.make_task(next_run)])
                    self.assertIsNone(self.status.nearest_task_cooling_down)

    def test_future_cooldown_keeps_the_sixty_minute_boundary(self):
        for seconds, expected in ((1, True), (3600, True), (3601, False)):
            with self.subTest(seconds=seconds):
                task = self.make_task(self.now + timedelta(seconds=seconds))
                self.status.config.waiting_task = [task]
                result = self.status.nearest_task_cooling_down
                self.assertIs(result, task if expected else None)

    def test_selects_nearest_enabled_cooldown_and_excludes_server_reset(self):
        # 将日更设在一小时内，确认它仍不会被误认为短期冷却。
        update = self.now + timedelta(minutes=10)
        nearest = self.make_task(self.now + timedelta(minutes=20), 'OpsiObscure')
        self.status.config.pending_task = [self.make_task(datetime(2026, 9, 7))]
        self.status.config.waiting_task = [
            self.make_task(self.now + timedelta(minutes=50), 'OpsiAbyssal'),
            self.make_task(update),
            self.make_task(self.now + timedelta(minutes=1), enabled=False),
            self.make_task(self.now + timedelta(minutes=2), 'Research'),
            nearest,
        ]
        with patch('module.os_handler.os_status.get_server_next_update', return_value=update):
            self.assertIs(self.status.nearest_task_cooling_down, nearest)

    def test_prevent_overflow_runs_meow_instead_of_requeueing_in_the_past(self):
        runner = OperationSiren.__new__(OperationSiren)
        owner = self.make_task(datetime(2026, 9, 7), 'OpsiPreventActionPointOverflow')
        runner.config = SimpleNamespace(
            task=owner,
            data={},
            pending_task=[owner, self.make_task(datetime(2026, 9, 7))],
            waiting_task=[],
            OpsiMeowfficerFarming_HazardLevel=5,
            OpsiMeowfficerFarming_TargetZone=0,
            OpsiMeowfficerFarming_StayInZone=False,
            OpsiTarget_TargetFarming=False,
            is_task_enabled=Mock(return_value=True),
            override=Mock(),
            bind=Mock(),
            temporary=lambda **kwargs: nullcontext(),
            task_delay=Mock(),
            task_stop=Mock(side_effect=TaskEnd),
        )
        with (
            patch.object(runner, '_get_prevent_action_point_overflow_thresholds', return_value=(200, 30)),
            patch.object(runner, '_get_prevent_action_point_overflow_task', return_value='OpsiMeowfficerFarming'),
            patch.object(runner, '_get_current_action_point_for_overflow', side_effect=[300, 20]),
            patch.object(runner, 'update_prevent_action_point_overflow_schedule') as reschedule,
            patch.object(runner, 'is_in_opsi_explore', return_value=False),
            patch.object(runner, '_meow_ap_check', return_value=True),
            patch.object(runner, '_meow_handle_normal_search') as search,
            patch('module.os.tasks.meowfficer_farming.get_os_reset_remain', return_value=22),
            patch('module.base.debug_clip.cleanup_clips_if_due'),
        ):
            with self.assertRaises(TaskEnd):
                runner.run_prevent_action_point_overflow()

        # 保留真实的代理上下文和短猫准备逻辑，仅替换设备交互。
        search.assert_called_once_with()
        runner.config.task_delay.assert_not_called()
        reschedule.assert_called_once_with(current_ap=20, enable=True)
        self.assertIs(runner.config.task, owner)
        self.assertFalse(runner.is_running_prevent_action_point_overflow_task())
        self.assertFalse(runner.is_running_smart_scheduling_task())
        self.assertFalse(hasattr(runner, runner.RUNTIME_ATTR_PREVENT_OVERFLOW_DELAY))


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

    def test_completed_explore_finalizes_before_startup_coin_switch(self):
        explore = OpsiExplore.__new__(OpsiExplore)
        explore.config = ExploreSchedulingConfig()
        explore.config.OS_EXPLORE_FILTER = '1'
        explore.config.OpsiExplore_LastZone = 1
        explore.config.OpsiExplore_ExploreProgress = None
        explore.config.OpsiExplore_SpecialRadar = False
        explore.config.Scheduler_NextRun = None
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
