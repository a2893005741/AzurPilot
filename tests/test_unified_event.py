"""统一活动开关与关卡候选的配置服务回归；使用临时配置目录，不连接游戏。"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from module.api.config_service import ConfigService, ROOT, stage_input_name
from module.api.protocol import ApiError, ConfigChange
from module.config.config_updater import EVENTS, ConfigUpdater

UNIFIED = 'EventGeneral.EventGeneral.UnifiedEvent'
LIGHT = 'event_20250227_cn'
ROSE = 'event_20250520_cn'


class UnifiedEventPatchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        for relative in ('config/template.json', 'module/config/argument/args.json',
                         'module/config/argument/menu.json', 'module/config/i18n/zh-CN.json'):
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
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


class UnifiedEventSchemaTests(unittest.TestCase):
    def test_options_match_event_tasks(self):
        args = json.loads((ROOT / 'module/config/argument/args.json').read_text(encoding='utf-8'))
        field = args['EventGeneral']['EventGeneral']['UnifiedEvent']
        self.assertEqual(field['value'], 'manual')
        self.assertEqual(field['option'], ['manual'] + args['Event']['Campaign']['Event']['option'])

    def test_stale_value_resets_on_load(self):
        updated = ConfigUpdater().config_update({'EventGeneral': {'EventGeneral': {'UnifiedEvent': 'event_19990101_cn'}}})
        self.assertEqual(updated['EventGeneral']['EventGeneral']['UnifiedEvent'], 'manual')
        updated = ConfigUpdater().config_update({'EventGeneral': {'EventGeneral': {'UnifiedEvent': LIGHT}}})
        self.assertEqual(updated['EventGeneral']['EventGeneral']['UnifiedEvent'], LIGHT)

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
        self.assertEqual(stages[LIGHT], ['A1', 'A2', 'A3', 'B1', 'B2', 'B3', 'C1', 'C2', 'C3', 'D1', 'D2', 'D3', 'SP'])
        self.assertEqual(stages['event_20250814_cn'][:2], ['HT1', 'HT2'])
        self.assertIn('T6', stages['event_20250814_cn'])
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
