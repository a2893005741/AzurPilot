"""活动图心情耗尽、独立延期和恢复轮转的回归测试。"""

import copy
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.campaign.run import CampaignRun
from module.campaign.campaign_base import CampaignBase
from module.combat.emotion import Emotion, EmotionRecoveryRequired
from module.config.config import AzurLaneConfig, name_to_function
from module.config.emotion_recovery import campaign_emotion_score, recover_emotion_config
from module.exception import CampaignEnd, ScriptEnd


class MemoryConfig(AzurLaneConfig):
    """沿用真实绑定、保存和调度方法，仅将文件存储替换为内存。"""

    @property
    def SCHEDULER_PRIORITY(self):
        return 'Restart > Commission > Event > Event2 > Event3 > Main'

    def __init__(self, store, command, clock):
        self.bound = {}
        self.store = store
        self.clock = clock
        self.config_name = 'test_campaign_emotion'
        self.modified = {}
        self.overridden = {}
        self.auto_update = True
        self.is_template_config = False
        self.task = name_to_function(command)
        self.load()
        self.bind(self.task)

    def read_file(self, name):
        return recover_emotion_config(copy.deepcopy(self.store), self.clock())

    def write_file(self, name, data):
        self.store.clear()
        self.store.update(copy.deepcopy(data))


class TestCampaignEmotionScheduling(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 9, 12)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for module in ('module.combat.emotion', 'module.config.config', 'module.config.config_updater'):
            self.stack.enter_context(patch(f'{module}.current_time', side_effect=lambda: self.now))
        self.stack.enter_context(patch.object(AzurLaneConfig, 'is_hoarding_task', False))
        self.stack.enter_context(patch('module.config.config.logger'))
        self.stack.enter_context(patch('module.combat.emotion.logger'))

    def task(self, name, value=0, recover='not_in_dormitory', fleet2=0, value2=119,
             order='fleet1_all_fleet2_standby', enabled=True, next_run=None):
        return {
            'Scheduler': {'Command': name, 'Enable': enabled,
                          'NextRun': next_run or self.now - timedelta(seconds=1)},
            'Emotion': {
                'Mode': 'calculate',
                'Fleet1Value': value, 'Fleet1Record': self.now,
                'Fleet1Recover': recover, 'Fleet1Control': 'prevent_green_face',
                'Fleet1Oath': False, 'Fleet1Onsen': False,
                'Fleet2Value': value2, 'Fleet2Record': self.now,
                'Fleet2Recover': 'not_in_dormitory', 'Fleet2Control': 'prevent_green_face',
                'Fleet2Oath': False, 'Fleet2Onsen': False,
            },
            'Fleet': {'Fleet1': 1, 'Fleet2': fleet2, 'FleetOrder': order},
            'Campaign': {'Use2xBook': False},
        }

    def config(self, store, name='Event'):
        return MemoryConfig(store, name, lambda: self.now)

    def runner(self, store, name='Event', battles=6):
        runner = object.__new__(CampaignRun)
        runner.config = self.config(store, name)
        runner.campaign = SimpleNamespace(
            config=self.config(store, name), _map_battle=battles,
            withdraw=Mock(), low_emotion_withdrawn=False,
        )
        runner.campaign.emotion = Emotion(runner.campaign.config)
        return runner

    def test_all_events_delay_independently_then_resume_when_ready(self):
        start = self.now
        store = {
            'Event': self.task('Event', 40),
            'Event2': self.task('Event2', 40, 'dormitory_floor_1'),
            'Event3': self.task('Event3', 40, 'dormitory_floor_2'),
            'Main': self.task('Main', 119),
        }
        queue = self.config(store)
        for name, minutes in [('Event', 36), ('Event2', 18), ('Event3', 14.4)]:
            queue.load()
            self.assertEqual(queue.get_next().command, name)
            runner = self.runner(store, name)
            self.assertTrue(runner.delay_event_for_emotion())
            expected = start + timedelta(minutes=minutes)
            self.assertEqual(store[name]['Scheduler']['NextRun'], expected)
            self.assertEqual(runner.config.data[name]['Scheduler']['NextRun'], expected)
            self.assertTrue(store[name]['Scheduler']['Enable'])
        queue.load()
        self.assertEqual(queue.get_next().command, 'Main')
        self.now = start + timedelta(minutes=14.4, seconds=1)
        queue.load()
        self.assertEqual(queue.get_next().command, 'Event3')
        self.assertFalse(self.runner(store, 'Event3').delay_event_for_emotion())
        self.assertEqual(store['Event']['Scheduler']['NextRun'], start + timedelta(minutes=36))

    def test_priority_uses_limiting_active_fleet_and_preserves_other_tasks(self):
        store = {
            'Event': self.task('Event', 35, fleet2=2, value2=150,
                               order='fleet1_mob_fleet2_boss'),
            'Event2': self.task('Event2', 60, fleet2=2, value2=60,
                                order='fleet1_mob_fleet2_boss'),
            'Restart': self.task('Restart'), 'Commission': self.task('Commission'),
            'Main': self.task('Main'),
        }
        queue = self.config(store)
        queue.get_next_task()
        self.assertEqual([t.command for t in queue.pending_task],
                         ['Restart', 'Commission', 'Event2', 'Event', 'Main'])

    def test_disabled_and_waiting_events_are_not_promoted(self):
        store = {'Event': self.task('Event', 50),
                 'Event2': self.task('Event2', 150, enabled=False),
                 'Event3': self.task('Event3', 150, next_run=self.now + timedelta(hours=1))}
        queue = self.config(store)
        self.assertEqual(queue.get_next().command, 'Event')
        self.assertEqual([t.command for t in queue.waiting_task], ['Event3'])

    def test_standby_fleet_neither_blocks_nor_inflates_priority(self):
        for order, first, second in [('fleet1_all_fleet2_standby', 60, 0),
                                      ('fleet1_standby_fleet2_all', 0, 60)]:
            with self.subTest(order=order):
                store = {'Event': self.task('Event', first, fleet2=2, value2=second, order=order)}
                self.assertFalse(self.runner(store).delay_event_for_emotion())
                self.assertEqual(campaign_emotion_score(store, 'Event', self.now), 20)

    def test_single_fleet_pays_for_entire_map_even_with_default_order(self):
        store = {'Event': self.task('Event', 40, order='fleet1_mob_fleet2_boss')}
        self.assertTrue(self.runner(store).delay_event_for_emotion())
        self.assertEqual(store['Event']['Scheduler']['NextRun'], self.now + timedelta(minutes=36))

    def test_dual_fleet_waits_for_slower_required_fleet(self):
        store = {'Event': self.task('Event', 40, 'dormitory_floor_2', fleet2=2,
                                   value2=0, order='fleet1_mob_fleet2_boss')}
        self.runner(store).delay_event_for_emotion()
        self.assertEqual(store['Event']['Scheduler']['NextRun'], self.now + timedelta(minutes=126))

    def test_double_book_and_recovery_bonuses_determine_delay(self):
        store = {'Event': self.task('Event', 40, 'dormitory_floor_1')}
        store['Event']['Campaign']['Use2xBook'] = True
        store['Event']['Emotion'].update(Fleet1Oath=True, Fleet1Onsen=True)
        self.runner(store).delay_event_for_emotion()
        self.assertEqual(store['Event']['Scheduler']['NextRun'], self.now + timedelta(minutes=24))

    def test_fractional_recovery_is_retained_and_target_not_rounded_early(self):
        store = {'Event': self.task('Event', 51, 'dormitory_floor_2')}
        store['Event']['Emotion']['Fleet1Record'] -= timedelta(seconds=30)
        start = self.now
        self.runner(store).delay_event_for_emotion()
        self.assertEqual(store['Event']['Scheduler']['NextRun'], start + timedelta(seconds=42))
        self.now += timedelta(seconds=42)
        self.assertFalse(self.runner(store).delay_event_for_emotion())

    def test_public_emotion_controls_all_linked_events(self):
        store = {'Event': self.task('Event', 150), 'Event2': self.task('Event2', 150),
                 'General': {'PublicEmotion': {'Enable': True, 'Tasks': 'Event, Event2',
                     'FleetValue': 40, 'FleetRecord': self.now, 'FleetControl': 'prevent_green_face',
                     'FleetRecover': 'dormitory_floor_1', 'FleetOath': False, 'FleetOnsen': False}}}
        for task in ('Event', 'Event2'):
            self.assertEqual(campaign_emotion_score(store, task, self.now), 0)
            self.assertTrue(self.runner(store, task).delay_event_for_emotion())
            self.assertEqual(store[task]['Scheduler']['NextRun'], self.now + timedelta(minutes=18))

    def test_ignore_mode_keeps_schedule_and_priority(self):
        store = {'Event': self.task('Event')}
        store['Event']['Emotion']['Mode'] = 'ignore'
        expected = store['Event']['Scheduler']['NextRun']
        self.assertFalse(self.runner(store).delay_event_for_emotion())
        self.assertIsNone(campaign_emotion_score(store, 'Event', self.now))
        self.assertEqual(store['Event']['Scheduler']['NextRun'], expected)

    def test_low_emotion_popup_does_not_wake_recovering_successor(self):
        expected = self.now + timedelta(hours=2)
        store = {'Event': self.task('Event', 75),
                 'Event2': self.task('Event2', 0, next_run=expected)}
        runner = self.runner(store)
        runner.campaign.low_emotion_withdrawn = True
        runner.campaign.withdraw.side_effect = CampaignEnd
        self.assertTrue(runner.handle_low_emotion_withdrawal())
        self.assertEqual(store['Event2']['Scheduler']['NextRun'], expected)
        self.assertEqual(store['Event']['Emotion']['Fleet1Value'], 0)
        self.assertEqual(store['Event']['Scheduler']['NextRun'], self.now + timedelta(minutes=156))
        runner.campaign.withdraw.assert_called_once_with(skip_first_screenshot=False)

    def test_mid_map_event_low_emotion_yields_without_sleeping(self):
        store = {'Event': self.task('Event', 40)}
        emotion = self.runner(store).campaign.emotion
        with patch('module.combat.emotion.sleep') as sleep:
            with self.assertRaises(EmotionRecoveryRequired):
                emotion.wait(1)
        sleep.assert_not_called()

    def test_mid_map_recovery_exits_run_without_counting_a_clear(self):
        store = {'Event': self.task('Event', 40), 'Event2': self.task('Event2', 60)}
        runner = self.runner(store)
        runner.device = Mock(has_cached_image=True)
        runner.handle_stage_name = Mock(return_value=('d3', 'event_test'))
        runner.load_campaign = Mock()
        runner.stage = 'd3'
        runner.disable_raid_on_event = Mock()
        runner.handle_commission_notice = Mock()
        runner.ui_page_appear = Mock(return_value=False)
        runner.triggered_stop_condition = Mock(return_value=False)
        campaign = runner.campaign
        campaign.device = runner.device
        campaign.event_time_limit_triggered = Mock(return_value=False)
        campaign.is_in_map = Mock(return_value=False)
        campaign.is_in_auto_search_menu = Mock(return_value=False)
        campaign.ensure_campaign_ui = Mock()
        campaign.ensure_auto_search_exit = Mock()
        campaign.run = Mock(side_effect=EmotionRecoveryRequired)
        campaign.withdraw.side_effect = CampaignEnd
        runner.run('d3', 'event_test')
        self.assertEqual(runner.run_count, 0)
        campaign.withdraw.assert_called_once_with(skip_first_screenshot=False)
        campaign.ensure_auto_search_exit.assert_called_once_with()
        self.assertEqual(store['Event']['Scheduler']['NextRun'], self.now + timedelta(minutes=36))
        self.assertEqual(self.config(store).get_next().command, 'Event2')

    def test_full_clear_refreshes_cached_battle_count_before_delaying(self):
        store = {'Event': self.task('Event', 40)}
        runner = self.runner(store)
        campaign = object.__new__(CampaignBase)
        campaign.config = self.config(store)
        campaign.MAP = SimpleNamespace(spawn_data=[{'battle': 0, 'enemy': 8},
                                                   {'battle': 5, 'boss': 1}])
        campaign.map_get_info = Mock(side_effect=lambda: setattr(campaign.config, 'MAP_CLEAR_ALL_THIS_TIME', True))
        self.assertEqual(campaign._map_battle, 6)
        runner.campaign = campaign
        self.assertTrue(runner.delay_event_for_emotion(refresh_map=True))
        self.assertEqual(campaign._map_battle, 9)
        self.assertEqual(store['Event']['Scheduler']['NextRun'], self.now + timedelta(minutes=54))

    def test_repeated_round_trip_after_resumed_event_is_exhausted(self):
        start = self.now
        store = {'Event': self.task('Event', 40), 'Event2': self.task('Event2', 40, 'dormitory_floor_1'),
                 'Main': self.task('Main', 119)}
        self.runner(store).delay_event_for_emotion()
        self.runner(store, 'Event2').delay_event_for_emotion()
        self.now += timedelta(minutes=18, seconds=1)
        self.assertEqual(self.config(store).get_next().command, 'Event2')
        resumed = self.runner(store, 'Event2')
        self.assertFalse(resumed.delay_event_for_emotion())
        for _ in range(6):
            resumed.campaign.emotion.reduce(1)
        self.assertTrue(resumed.delay_event_for_emotion())
        self.assertEqual(self.config(store).get_next().command, 'Main')
        self.assertEqual(store['Event']['Scheduler']['NextRun'], start + timedelta(minutes=36))
        self.now = start + timedelta(minutes=36, seconds=1)
        self.assertIn(self.config(store).get_next().command, ('Event', 'Event2'))

    def test_score_recovers_stale_records_without_mutating_them(self):
        store = {'Event': self.task('Event', 40)}
        old = copy.deepcopy(store)
        self.assertEqual(campaign_emotion_score(store, 'Event', self.now + timedelta(minutes=30)), 10)
        self.assertEqual(store, old)

    def test_recovery_target_rounds_up_to_a_whole_second(self):
        store = {'Event': self.task('Event', 51, 'dormitory_floor_2')}
        store['Event']['Emotion'].update(Fleet1Oath=True, Fleet1Onsen=True)
        self.runner(store).delay_event_for_emotion()
        self.assertEqual(store['Event']['Scheduler']['NextRun'], self.now + timedelta(seconds=52))
        self.now += timedelta(seconds=52)
        self.assertFalse(self.runner(store).delay_event_for_emotion())

    def test_emotion_takes_precedence_over_oil_delay(self):
        runner = self.runner({'Event': self.task('Event', 40)})
        runner.run_limit = 0
        runner.config.StopCondition_ReachLevel = False
        runner.delay_event_for_emotion = Mock(return_value=True)
        runner.get_oil = Mock()
        self.assertTrue(runner.triggered_stop_condition())
        runner.get_oil.assert_not_called()
        runner.delay_event_for_emotion.assert_called_once_with(refresh_map=True)

    def test_preflight_delays_using_real_emotion_check(self):
        store = {'Event': self.task('Event', 40)}
        emotion = Emotion(self.config(store))
        with self.assertRaises(ScriptEnd):
            emotion.check_reduce(6)
        self.assertEqual(store['Event']['Scheduler']['NextRun'], self.now + timedelta(minutes=36))


if __name__ == '__main__':
    unittest.main()
