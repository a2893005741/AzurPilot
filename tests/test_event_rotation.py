"""活动队列按恢复能力逐局轮换，覆盖真实配置读写与长时间混合恢复。"""

from collections import Counter
from datetime import timedelta
import unittest
from unittest.mock import Mock, patch

from dev_tools.emotion_simulate import LuaOracle, ShipSpec
from module.base.emotion import EMOTION_ROTATION_TASKS
from module.config.event_rotation import record_event_rotation, rotation_settings
from module.exception import ScriptEnd
from tests import test_campaign_emotion_scheduling as scheduling


class TestEventRotation(unittest.TestCase):
    setUp = scheduling.TestCampaignEmotionScheduling.setUp
    task = scheduling.TestCampaignEmotionScheduling.task
    state = scheduling.TestCampaignEmotionScheduling.state
    config = scheduling.TestCampaignEmotionScheduling.config
    runner = scheduling.TestCampaignEmotionScheduling.runner

    def pool(self, recoveries):
        store = {}
        for i, recovery in enumerate(recoveries):
            name = EMOTION_ROTATION_TASKS[i]
            value = 119 if recovery == 'not_in_dormitory' else 150
            store[name] = self.task(name, value, recovery)
            store[name]['Campaign'].update(Name='T6', Event='event_test', Mode='normal')
            store[name]['Fleet']['Fleet1'] = i + 1
        return store

    def finish(self, store, name, seconds=324, oracle=None):
        runner = self.runner(store, name, battles=7)
        settings = rotation_settings(store, name)
        self.assertFalse(runner.delay_event_for_emotion())
        for _ in range(7):
            self.now += timedelta(seconds=seconds / 7)
            if oracle is not None:
                origin, reference = oracle
                reference.advance(round((self.now - origin).total_seconds() * 1_000_000))
                reference.consume(0, 2)
                self.assertGreaterEqual(reference.values[0], 40)
            runner.campaign.emotion.reduce(1)
        record_event_rotation(runner.campaign.config, (14, 0), seconds, self.now, settings)

    def test_five_equal_fleets_rotate_after_every_map(self):
        store = self.pool(['dormitory_floor_2'] * 5)
        selected = []
        for _ in range(15):
            name = self.config(store).get_next().command
            selected.append(name)
            self.finish(store, name)
        self.assertEqual(selected, list(EMOTION_ROTATION_TASKS) * 3)

    def test_full_119_fleet_is_not_hidden_by_150_cap(self):
        store = self.pool(['dormitory_floor_2', 'not_in_dormitory'])
        self.finish(store, 'Event')
        self.assertEqual(self.config(store).get_next().command, 'Event2')

    def test_five_mixed_fleets_run_72_hours_without_emotion_wait(self):
        for seconds in (324, 280):
            with self.subTest(seconds=seconds):
                store = self.pool(['dormitory_floor_2'] * 3 + ['not_in_dormitory'] * 2)
                origin = self.now
                oracles = {name: LuaOracle(ShipSpec(task['Emotion']['Fleet1Recover'], False),
                                          task['Emotion']['Fleet1Value'], 0, i * 61_000_000)
                           for i, (name, task) in enumerate(store.items())}
                selected = Counter()
                for _ in range(int(72 * 3600 / seconds)):
                    name = self.config(store).get_next().command
                    selected[name] += 1
                    self.finish(store, name, seconds, (origin, oracles[name]))
                self.assertEqual(len(selected), 5)
                self.assertGreater(selected['Event'], selected['Event4'])
                self.assertLess(abs(selected['Event4'] - selected['Event5']), 3)

    def test_stale_map_cost_does_not_block_changed_stage(self):
        store = self.pool(['dormitory_floor_2'] * 2)
        self.finish(store, 'Event')
        store['Event']['Campaign']['Name'] = 'T4'
        store['Event']['EventRotation']['Stats']['costs'] = [150, 0]
        store['Event2']['Emotion']['Mode'] = 'ignore'
        self.assertEqual(self.config(store).get_next().command, 'Event')

    def test_recorder_uses_effective_map_cost(self):
        store = self.pool(['dormitory_floor_2'])
        runner = self.runner(store)
        runner.campaign.config = self.config(store)
        with patch('module.campaign.run.record_event_rotation') as record:
            runner.record_event_rotation(324, rotation_settings(store, 'Event'))
        record.assert_called_once()
        self.assertEqual(record.call_args.args[1], (12, 0))

    def test_new_queues_preserve_cooldowns_and_other_task_positions(self):
        store = self.pool(['dormitory_floor_2'] * 5)
        store['Event4']['Scheduler']['Enable'] = False
        store['Event5']['Scheduler']['NextRun'] = self.now + timedelta(hours=1)
        store['Commission'] = self.task('Commission')
        queue = self.config(store)
        queue.get_next_task()
        self.assertEqual([task.command for task in queue.pending_task],
                         ['Commission', 'Event', 'Event2', 'Event3'])
        self.assertEqual([task.command for task in queue.waiting_task], ['Event5'])

    def test_runnable_map_wins_over_nearly_full_but_insufficient_fleet(self):
        store = self.pool(['dormitory_floor_2', 'not_in_dormitory'])
        self.finish(store, 'Event')
        self.finish(store, 'Event2')
        # 119 队伍虽然更接近自己的上限，开启保持经验加成后也不能出击。
        store['Event2']['Emotion']['Fleet1Control'] = 'keep_exp_bonus'
        self.assertEqual(self.config(store).get_next().command, 'Event')

    def test_completed_record_survives_reload_and_ignored_mode_keeps_slot(self):
        store = self.pool(['dormitory_floor_2'] * 3)
        self.finish(store, 'Event')
        self.assertGreater(store['Event']['EventRotation']['Stats']['duration'], 0)
        store['Event']['Emotion']['Mode'] = 'ignore'
        self.assertEqual(self.config(store).get_next().command, 'Event')

    def test_settings_changed_inside_map_do_not_poison_new_stage_stats(self):
        store = self.pool(['dormitory_floor_2'])
        config = self.config(store)
        settings = rotation_settings(store, 'Event')
        config.cross_set('Event.Campaign.Name', 'T4')
        record_event_rotation(config, (14, 0), 324, self.now, settings)
        self.assertNotIn('EventRotation', store['Event'])

    def test_real_runner_records_complete_map_but_not_interrupted_attempt(self):
        for outcome in (True, ScriptEnd('测试中断')):
            with self.subTest(outcome=outcome):
                store = self.pool(['dormitory_floor_2'])
                runner = self.runner(store, battles=7)
                runner.device = Mock(has_cached_image=True)
                runner.handle_stage_name = Mock(return_value=('t6', 'event_test'))
                runner.load_campaign = Mock()
                runner.stage = 't6'
                runner.disable_raid_on_event = Mock()
                runner.handle_commission_notice = Mock()
                runner.ui_page_appear = Mock(return_value=False)
                runner.triggered_stop_condition = Mock(return_value=False)
                runner.config.task_switched = Mock(return_value=False)
                campaign = runner.campaign
                campaign.device = runner.device
                campaign.event_time_limit_triggered = Mock(return_value=False)
                campaign.is_in_map = Mock(return_value=False)
                campaign.is_in_auto_search_menu = Mock(return_value=False)
                campaign.ensure_campaign_ui = Mock()
                campaign.ensure_auto_search_exit = Mock()
                campaign.run = Mock(return_value=True if outcome is True else None,
                                    side_effect=None if outcome is True else outcome)
                with patch('module.campaign.run.monotonic', side_effect=[10, 334, 335]):
                    runner._run('t6', 'event_test', total=1)
                if outcome is True:
                    stats = store['Event']['EventRotation']['Stats']
                    self.assertEqual(stats['costs'], [14, 0])
                    self.assertEqual(stats['duration'], 324)
                    runner.config.task_switched.assert_called_once()
                else:
                    self.assertNotIn('EventRotation', store['Event'])
