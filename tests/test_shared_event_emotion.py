"""活动图按港区舰队共享心情，真实保存事务与 API 编辑使用同一规则。"""

import tempfile
import unittest

from dev_tools.emotion_simulate import LuaOracle, ShipSpec
from module.api.config_service import ConfigService
from module.api.protocol import ApiError, ConfigChange
from module.combat.emotion import Emotion
from module.combat.emotion_state import EmotionRecoveryState
from tests import test_campaign_emotion_scheduling as scheduling
from tests.test_api import fixture


class SharedEventEmotionTests(unittest.TestCase):
    setUp = scheduling.TestCampaignEmotionScheduling.setUp
    task = scheduling.TestCampaignEmotionScheduling.task
    state = scheduling.TestCampaignEmotionScheduling.state
    config = scheduling.TestCampaignEmotionScheduling.config

    def pool(self):
        store = {}
        for name, number in [('Event', 3), ('Event2', 4)]:
            store[name] = self.task(name, 150, 'dormitory_floor_2', fleet2=2,
                                    order='fleet1_mob_fleet2_boss')
            store[name]['Fleet']['Fleet1'] = number
            store[name]['EventRotation'] = {'SharedFleet': 'fleet2'}
        return store

    def test_shared_boss_pays_every_task_once_and_mob_remains_independent(self):
        store = self.pool()
        for name in ('Event', 'Event2', 'Event'):
            Emotion(self.config(store, name)).reduce(2)
        self.assertEqual(store['Event']['Emotion']['Fleet2Value'], 113)
        self.assertEqual(store['Event2']['Emotion']['Fleet2Value'], 113)
        Emotion(self.config(store, 'Event')).reduce(1)
        self.assertEqual(store['Event']['Emotion']['Fleet1Value'], 148)
        self.assertEqual(store['Event2']['Emotion']['Fleet1Value'], 150)

    def test_reused_emotion_instance_reads_latest_shared_record(self):
        store = self.pool()
        first = Emotion(self.config(store, 'Event'))
        second = Emotion(self.config(store, 'Event2'))
        first.reduce(2)
        second.reduce(2)
        first.reduce(2)
        self.assertEqual(store['Event']['Emotion']['Fleet2Value'], 113)
        self.assertEqual(store['Event2']['Emotion']['Fleet2Value'], 113)

    def test_actual_fleet_number_can_be_slot_two_or_slot_one(self):
        store = self.pool()
        store['Event2']['Fleet'].update(Fleet1=2, Fleet2=5)
        store['Event2']['Emotion']['Fleet1Value'] = 119
        store['Event2']['Emotion']['Fleet1Recover'] = 'not_in_dormitory'
        store['Event2']['Emotion']['Fleet1RecoveryState'] = self.state(119, 'not_in_dormitory')
        store['Event2']['EventRotation']['SharedFleet'] = 'fleet1'
        Emotion(self.config(store, 'Event')).reduce(2)
        self.assertEqual(store['Event2']['Emotion']['Fleet1Value'], 117)

    def test_reset_and_extra_penalty_reach_all_shared_tasks(self):
        store = self.pool()
        emotion = Emotion(self.config(store, 'Event'))
        emotion.reduce(2, shipwreck=True)
        self.assertEqual(store['Event2']['Emotion']['Fleet2Value'], 109)
        emotion.reset_fleets([emotion.fleet_2])
        self.assertEqual(store['Event2']['Emotion']['Fleet2Value'], 0)
        self.assertEqual(store['Event2']['Emotion']['Fleet1Value'], 150)

    def test_off_and_different_fleet_ids_keep_independent_books(self):
        for option, fleet in [('none', 2), ('fleet2', 5)]:
            with self.subTest(option=option, fleet=fleet):
                store = self.pool()
                store['Event2']['EventRotation']['SharedFleet'] = option
                store['Event2']['Fleet']['Fleet2'] = fleet
                Emotion(self.config(store, 'Event')).reduce(2)
                self.assertEqual(store['Event2']['Emotion']['Fleet2Value'], 119)

    def test_stale_pending_save_cannot_undo_new_shared_consumption(self):
        store = self.pool()
        stale = self.config(store, 'Event')
        stale.auto_update = False
        emotion = Emotion(stale)
        emotion.update()
        emotion.fleet_2.consume(2)
        emotion.record()
        Emotion(self.config(store, 'Event2')).reduce(2)
        stale.save()
        self.assertEqual(store['Event']['Emotion']['Fleet2Value'], 117)
        self.assertEqual(store['Event2']['Emotion']['Fleet2Value'], 117)

    def test_turning_off_sharing_rejects_old_in_flight_shared_snapshot(self):
        store = self.pool()
        stale = self.config(store, 'Event')
        stale.auto_update = False
        emotion = Emotion(stale)
        emotion.update()
        emotion.fleet_2.consume(2)
        emotion.record()
        store['Event']['EventRotation']['SharedFleet'] = 'none'
        stale.save()
        self.assertEqual(store['Event']['Emotion']['Fleet2Value'], 119)
        self.assertEqual(store['Event2']['Emotion']['Fleet2Value'], 119)

    def test_shared_boss_can_block_all_maps_without_spending_mob_emotion(self):
        store = self.pool()
        for task in store.values():
            task['Emotion']['Fleet2Value'] = 40
            task['Emotion']['Fleet2RecoveryState'] = self.state(40, 'not_in_dormitory')
        runner = scheduling.TestCampaignEmotionScheduling.runner(self, store)
        self.assertTrue(runner.delay_event_for_emotion())
        self.assertEqual(store['Event']['Emotion']['Fleet1Value'], 150)
        self.assertEqual(store['Event2']['Emotion']['Fleet2Value'], 40)

    def test_runtime_join_refreshes_bound_values_without_restoring_old_morale(self):
        store = self.pool()
        store['Event2']['EventRotation']['SharedFleet'] = 'none'
        Emotion(self.config(store, 'Event')).reduce(2)
        config = self.config(store, 'Event2')
        config.EventRotation_SharedFleet = 'fleet2'
        self.assertEqual(config.Emotion_Fleet2Value, 117)
        self.assertEqual(store['Event2']['Emotion']['Fleet2Value'], 117)

    def test_both_slots_share_only_their_matching_port_fleet(self):
        store = self.pool()
        store['Event2']['Fleet']['Fleet1'] = 3
        for task in store.values():
            task['EventRotation']['SharedFleet'] = 'both'
        Emotion(self.config(store, 'Event')).reduce(1)
        self.assertEqual(store['Event2']['Emotion']['Fleet1Value'], 148)
        self.assertEqual(store['Event2']['Emotion']['Fleet2Value'], 119)

    def test_shared_recovery_is_applied_once_across_cached_task_objects(self):
        from datetime import timedelta
        store = self.pool()
        for task in store.values():
            task['Emotion']['Fleet2Value'] = 80
            task['Emotion']['Fleet2RecoveryState'] = self.state(80, 'not_in_dormitory')
        first, second = (Emotion(self.config(store, name)) for name in ('Event', 'Event2'))
        first.reduce(2)
        self.now += timedelta(minutes=6)
        second.reduce(2)
        # 港区未婚恢复一批 2 点，再消耗 2 点；不能按任务各恢复一批。
        self.assertEqual(store['Event']['Emotion']['Fleet2Value'], 78)
        self.assertEqual(store['Event2']['Emotion']['Fleet2Value'], 78)

    def test_four_mob_queues_and_one_shared_boss_match_independent_12_hour_model(self):
        from datetime import timedelta
        store = self.pool()
        for name, number in [('Event3', 5), ('Event4', 6)]:
            store[name] = self.task(name, 150, 'dormitory_floor_2', fleet2=2,
                                    order='fleet1_mob_fleet2_boss')
            store[name]['Fleet']['Fleet1'] = number
            store[name]['EventRotation'] = {'SharedFleet': 'fleet2'}
        for task in store.values():
            task['Emotion']['Fleet2Oath'] = True
            task['Emotion']['Fleet2RecoveryState'] = EmotionRecoveryState.calibrate(
                119, self.now, 'not_in_dormitory', True, False).export()
        origin = self.now
        boss = LuaOracle(ShipSpec('not_in_dormitory', True), 119, 0, 187_000_000)
        tasks = list(store)
        for i in range(180):
            name = self.config(store).get_next().command
            runner = scheduling.TestCampaignEmotionScheduling.runner(self, store, name, battles=7)
            self.assertFalse(runner.delay_event_for_emotion())
            for battle in range(7):
                self.now += timedelta(seconds=240 / 7)
                runner.campaign.emotion.reduce(1 if battle < 6 else 2)
            boss.advance(round((self.now - origin).total_seconds() * 1_000_000))
            boss.consume(0, 2)
            for task in tasks:
                self.assertEqual(store[task]['Emotion']['Fleet2Value'],
                                 store[name]['Emotion']['Fleet2Value'])
            state = runner.campaign.emotion.fleet_2.state
            self.assertLessEqual(state.lower, boss.values[0])
            self.assertGreaterEqual(state.upper, boss.values[0])


class SharedEventEmotionApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = ConfigService(fixture(self.temp.name))
        self.patch(('Event.Fleet.Fleet1', 3), ('Event.Fleet.Fleet2', 2),
                   ('Event2.Fleet.Fleet1', 4), ('Event2.Fleet.Fleet2', 2))

    def patch(self, *changes):
        return self.service.patch('testpilot', None, [ConfigChange(path=k, value=v) for k, v in changes])['values']

    def join(self):
        self.patch(('Event.EventRotation.SharedFleet', 'fleet2'), ('Event.Emotion.Fleet2Value', 85))
        return self.patch(('Event2.EventRotation.SharedFleet', 'fleet2'))

    def test_join_inherits_existing_book_and_recovery_settings(self):
        self.patch(('Event.Emotion.Fleet2Oath', True), ('Event2.Emotion.Fleet2Recover', 'dormitory_floor_2'))
        data = self.join()
        for suffix in ('Value', 'Record', 'RecoveryState', 'Recover', 'Oath', 'Onsen'):
            self.assertEqual(data['Event']['Emotion']['Fleet2' + suffix],
                             data['Event2']['Emotion']['Fleet2' + suffix])
        self.assertEqual(data['Event2']['Emotion']['Fleet2Value'], 85)
        self.assertTrue(data['Event2']['Emotion']['Fleet2Oath'])
        self.assertEqual(data['Event2']['Emotion']['Fleet2Recover'], 'not_in_dormitory')

    def test_calibration_and_condition_edit_propagate_but_control_is_local(self):
        self.join()
        data = self.patch(('Event2.Emotion.Fleet2Value', 73), ('Event2.Emotion.Fleet2Oath', True),
                          ('Event2.Emotion.Fleet2Control', 'prevent_red_face'))
        self.assertEqual(data['Event']['Emotion']['Fleet2Value'], 73)
        self.assertTrue(data['Event']['Emotion']['Fleet2Oath'])
        self.assertEqual(data['Event']['Emotion']['Fleet2RecoveryState']['signature'],
                         ['not_in_dormitory', True, False])
        self.assertNotEqual(data['Event']['Emotion']['Fleet2Control'], 'prevent_red_face')
        data = self.patch(('Event.Emotion.Fleet2Recover', 'dormitory_floor_1'))
        self.assertIsNone(data['Event2']['Emotion']['Fleet2RecoveryState'])
        self.assertEqual(data['Event2']['Emotion']['Fleet2Recover'], 'dormitory_floor_1')

    def test_leaving_keeps_last_value_and_stops_future_updates(self):
        self.join()
        self.patch(('Event2.EventRotation.SharedFleet', 'none'))
        data = self.patch(('Event.Emotion.Fleet2Value', 60))
        self.assertEqual(data['Event']['Emotion']['Fleet2Value'], 60)
        self.assertEqual(data['Event2']['Emotion']['Fleet2Value'], 85)

    def test_reject_conflicting_edits_and_public_or_invalid_fleet_atomically(self):
        self.join()
        for changes in [
            [('Event.Emotion.Fleet2Value', 60), ('Event2.Emotion.Fleet2Value', 80)],
            [('General.PublicEmotion.Enable', True), ('General.PublicEmotion.Tasks', 'Event')],
            [('Event.Fleet.Fleet2', 0)],
            [('Event.Emotion.Mode', 'ignore')],
        ]:
            before = self.service.path('testpilot').read_bytes()
            with self.subTest(changes=changes), self.assertRaises(ApiError):
                self.patch(*changes)
            self.assertEqual(self.service.path('testpilot').read_bytes(), before)

    def test_mapping_change_does_not_export_old_fleet_book_to_new_group(self):
        self.join()
        self.patch(('Event3.Fleet.Fleet2', 5), ('Event3.EventRotation.SharedFleet', 'fleet2'),
                   ('Event3.Emotion.Fleet2Value', 65))
        data = self.patch(('Event2.Fleet.Fleet2', 5))
        self.assertEqual(data['Event2']['Emotion']['Fleet2Value'], 65)
        self.assertEqual(data['Event']['Emotion']['Fleet2Value'], 85)

    def test_reading_and_migration_do_not_write_shared_records(self):
        self.join()
        original = self.service.path('testpilot').read_bytes()
        first = self.service.get('testpilot')
        self.assertEqual(self.service.get('testpilot'), first)
        self.assertEqual(self.service.path('testpilot').read_bytes(), original)

    def test_join_with_condition_edit_keeps_latest_shared_value(self):
        self.join()
        self.patch(('Event2.EventRotation.SharedFleet', 'none'), ('Event2.Emotion.Fleet2Value', 119))
        data = self.patch(('Event2.EventRotation.SharedFleet', 'fleet2'), ('Event2.Emotion.Fleet2Oath', True))
        self.assertEqual(data['Event']['Emotion']['Fleet2Value'], 85)
        self.assertTrue(data['Event']['Emotion']['Fleet2Oath'])

    def test_join_with_calibration_uses_inherited_recovery_conditions(self):
        self.patch(('Event.EventRotation.SharedFleet', 'fleet2'), ('Event.Emotion.Fleet2Oath', True))
        self.patch(('Event2.Emotion.Fleet2Recover', 'dormitory_floor_2'))
        data = self.patch(('Event2.EventRotation.SharedFleet', 'fleet2'), ('Event2.Emotion.Fleet2Value', 75))
        state = data['Event']['Emotion']['Fleet2RecoveryState']
        self.assertEqual(state['signature'], ['not_in_dormitory', True, False])
        self.assertEqual(data['Event']['Emotion']['Fleet2Value'], 75)

    def test_new_untracked_fleet_requires_measurement_on_mapping_change(self):
        self.join()
        with self.assertRaises(ApiError):
            self.patch(('Event2.Fleet.Fleet2', 5))
        data = self.patch(('Event2.Fleet.Fleet2', 5), ('Event2.Emotion.Fleet2Value', 65))
        self.assertEqual(data['Event']['Emotion']['Fleet2Value'], 85)
        self.assertEqual(data['Event2']['Emotion']['Fleet2Value'], 65)
