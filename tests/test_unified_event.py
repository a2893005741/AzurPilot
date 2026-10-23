"""统一活动开关与关卡候选的配置服务回归；使用临时配置目录，不连接游戏。"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from module.api.config_service import ConfigService, ROOT, stage_input_name
from module.api.protocol import ApiError, ConfigChange
from module.config.config_updater import EVENTS, GEMS_FARMINGS, ConfigUpdater
from module.config.task_priority import parse_task_priority

UNIFIED = 'EventGeneral.EventGeneral.UnifiedEvent'
# 两个仍有地图文件的活动；保存用例把它们注入临时 args 的 cn 候选，不依赖当期复刻列表。
LIGHT = 'event_20260908_cn'
ROSE = 'event_20261022_cn'


class UnifiedEventPatchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        for relative in ('config/template.json', 'module/config/argument/args.json',
                         'module/config/argument/menu.json', 'module/config/i18n/zh-CN.json'):
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
        args_path = root / 'module/config/argument/args.json'
        args = json.loads(args_path.read_text(encoding='utf-8'))
        for task in EVENTS + GEMS_FARMINGS:
            # 低耗保留主线候选，只验证跟随规则；运行器把低耗主线刷新为活动的行为不在此范围。
            prefix = ['campaign_main'] if task in GEMS_FARMINGS else []
            args[task]['Campaign']['Event']['option_cn'] = prefix + [LIGHT, ROSE]
        args_path.write_text(json.dumps(args, ensure_ascii=False), encoding='utf-8')
        shutil.copyfile(root / 'config/template.json', root / 'config/testpilot.json')
        self.path = root / 'config/testpilot.json'
        self.service = ConfigService(root)

    def tearDown(self):
        self.directory.cleanup()

    def values(self):
        return self.service.get('testpilot')['values']

    def patch(self, *changes):
        self.service.patch('testpilot', None, [ConfigChange(path=path, value=value) for path, value in changes])

    def set_raw(self, task, event):
        data = json.loads(self.path.read_text(encoding='utf-8'))
        data.setdefault(task, {}).setdefault('Campaign', {})['Event'] = event
        self.path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

    def test_unified_event_switches_every_event_task(self):
        self.patch((UNIFIED, LIGHT))
        values = self.values()
        self.assertEqual(values['EventGeneral']['EventGeneral']['UnifiedEvent'], LIGHT)
        for task in EVENTS:
            with self.subTest(task=task):
                self.assertEqual(values[task]['Campaign']['Event'], LIGHT)
        self.patch((UNIFIED, ROSE))
        self.assertEqual({self.values()[task]['Campaign']['Event'] for task in EVENTS}, {ROSE})

    def test_old_config_adds_two_disabled_slots_without_replacing_existing_fleets(self):
        old = self.values()
        for name in ('Event4', 'Event5'):
            old.pop(name)
        old['Event']['Fleet']['Fleet1'] = 4
        old['Event2']['Fleet']['Fleet1'] = 5
        old['Event3']['Fleet']['Fleet1'] = 6
        priority = 'Commission > Event3 > Event > Event2 > Main'
        old['General']['YukikazeTaskManager']['TaskPriorityAdjustment'] = priority
        migrated = ConfigUpdater().config_update(old)
        self.assertEqual([migrated[name]['Fleet']['Fleet1'] for name in ('Event', 'Event2', 'Event3')],
                         [4, 5, 6])
        for name in ('Event4', 'Event5'):
            self.assertFalse(migrated[name]['Scheduler']['Enable'])
            self.assertEqual(migrated[name]['Scheduler']['Command'], name)
            self.assertEqual(migrated[name]['Emotion']['Fleet1Recover'], 'not_in_dormitory')
        merged = parse_task_priority(migrated['General']['YukikazeTaskManager']['TaskPriorityAdjustment'])
        self.assertEqual([name for name in merged if name in parse_task_priority(priority)],
                         parse_task_priority(priority))
        self.assertTrue({'Event4', 'Event5'}.issubset(merged))

    def test_rotation_runtime_record_cannot_be_edited_from_config_api(self):
        with self.assertRaises(ApiError) as caught:
            self.patch(('Event5.EventRotation.Stats', {'duration': 1}))
        self.assertEqual(caught.exception.code, 'READ_ONLY')

    def test_low_cost_tasks_follow_only_when_farming_event(self):
        self.set_raw('GemsFarming', 'campaign_main')
        self.set_raw('ThreeOilLowCost', ROSE)
        self.patch((UNIFIED, LIGHT))
        values = self.values()
        self.assertEqual(values['GemsFarming']['Campaign']['Event'], 'campaign_main')
        self.assertEqual(values['ThreeOilLowCost']['Campaign']['Event'], LIGHT)

    def test_manual_keeps_each_task(self):
        self.patch((UNIFIED, LIGHT))
        self.patch(('Event2.Campaign.Event', ROSE))
        values = self.values()
        # 单独改任务后退回分别选择，其他任务保持原值。
        self.assertEqual(values['EventGeneral']['EventGeneral']['UnifiedEvent'], 'manual')
        self.assertEqual(values['Event2']['Campaign']['Event'], ROSE)
        self.assertEqual(values['Event']['Campaign']['Event'], LIGHT)
        self.patch((UNIFIED, 'manual'))
        self.assertEqual(self.values()['Event2']['Campaign']['Event'], ROSE)

    def test_same_value_on_single_task_keeps_unified(self):
        self.patch((UNIFIED, LIGHT))
        self.patch(('EventA.Campaign.Event', LIGHT))
        self.assertEqual(self.values()['EventGeneral']['EventGeneral']['UnifiedEvent'], LIGHT)

    def test_unified_wins_when_saved_together(self):
        self.patch((UNIFIED, LIGHT), ('Event.Campaign.Event', ROSE))
        values = self.values()
        self.assertEqual(values['EventGeneral']['EventGeneral']['UnifiedEvent'], LIGHT)
        self.assertEqual(values['Event']['Campaign']['Event'], LIGHT)

    def test_rejects_unknown_event(self):
        with self.assertRaises(ApiError):
            self.patch((UNIFIED, 'event_19990101_cn'))
        with self.assertRaises(ApiError):
            self.patch((UNIFIED, 'campaign_main'))

    def test_candidates_follow_instance_server(self):
        self.assertEqual(self.service.get('testpilot')['options'][UNIFIED], ['manual', LIGHT, ROSE])
        self.patch((UNIFIED, ROSE))
        # 切到台服后统一活动不再是当前候选：读取时回到分别选择，且不能再显式选择跨服活动。
        self.patch(('Alas.Emulator.PackageName', 'com.hkmanjuu.azurlane.gp'))
        self.assertEqual(self.values()['EventGeneral']['EventGeneral']['UnifiedEvent'], 'manual')
        options = self.service.get('testpilot')['options']
        self.assertEqual(options[UNIFIED], ['manual'] + options['Event.Campaign.Event'])
        with self.assertRaises(ApiError):
            self.patch((UNIFIED, ROSE))


class UnifiedEventSchemaTests(unittest.TestCase):
    def test_options_match_event_tasks(self):
        args = json.loads((ROOT / 'module/config/argument/args.json').read_text(encoding='utf-8'))
        field = args['EventGeneral']['EventGeneral']['UnifiedEvent']
        self.assertEqual(field['value'], 'manual')
        self.assertEqual(field['option'], ['manual'] + args['Event']['Campaign']['Event']['option'])

    def test_stale_value_resets_on_load(self):
        updated = ConfigUpdater().config_update({'EventGeneral': {'EventGeneral': {'UnifiedEvent': 'event_19990101_cn'}}})
        self.assertEqual(updated['EventGeneral']['EventGeneral']['UnifiedEvent'], 'manual')
        current = json.loads((ROOT / 'module/config/argument/args.json').read_text(encoding='utf-8'))[
            'Event']['Campaign']['Event']['option_cn'][0]
        updated = ConfigUpdater().config_update({'EventGeneral': {'EventGeneral': {'UnifiedEvent': current}}})
        self.assertEqual(updated['EventGeneral']['EventGeneral']['UnifiedEvent'], current)

    def test_translations_are_complete(self):
        options = json.loads((ROOT / 'module/config/argument/args.json').read_text(encoding='utf-8'))[
            'EventGeneral']['EventGeneral']['UnifiedEvent']['option']
        for language in ('zh-CN', 'zh-MIAO', 'en-US', 'ja-JP', 'zh-TW'):
            with self.subTest(language=language):
                data = json.loads((ROOT / 'module/config/i18n' / f'{language}.json').read_text(encoding='utf-8'))
                field = data['EventGeneral']['UnifiedEvent']
                for key in ['name', 'help'] + options:
                    self.assertNotIn('EventGeneral.UnifiedEvent', field[key])
                    self.assertNotEqual(field[key], key)

    def test_stage_suggestions_follow_map_files(self):
        stages = ConfigService(ROOT).schema()['stages']
        self.assertEqual(stages[LIGHT], ['A1', 'A2', 'A3', 'B1', 'B2', 'B3', 'C1', 'C2', 'C3', 'D1', 'D2', 'D3',
                                         'D3-3', 'SP'])
        self.assertIn('T1', stages[ROSE])
        self.assertIn('T6', stages[ROSE])
        main = stages['campaign_main']
        self.assertLess(main.index('7-2'), main.index('12-4'))
        self.assertNotIn('CAMPAIGN-BASE', main)

    def test_stage_input_name_matches_runtime(self):
        from module.handler.fast_forward import to_map_file_name
        for file in ('a1', 'sp', 'ht3', 'd3_3', 'campaign_7_2', 'campaign_1_1_f'):
            with self.subTest(file=file):
                self.assertEqual(to_map_file_name(stage_input_name(file)).replace('-', '_'), file)


if __name__ == '__main__':
    unittest.main()
