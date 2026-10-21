"""手动运行通过真实配置事务、接口和调度循环优先执行，不连接游戏。"""
import json
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.api.config_service import ConfigService
from module.api.protocol import ConfigChange
from module.api.runtime_service import RuntimeService
from module.config.config import TaskEnd
from tests import test_scheduler_live_loop as live


class ManualRunTests(unittest.TestCase):
    setUp = live.LiveLoopTests.setUp
    virtual_wait = live.LiveLoopTests.virtual_wait
    apply = live.LiveLoopTests.apply
    program = live.LiveLoopTests.program

    def request(self, task='Main'):
        configs = ConfigService(self.root)
        configs.patch('testpilot', None, [ConfigChange(
            path=f'{task}.Scheduler.NextRun', value='2020-01-01 00:00:00')])

    def test_manual_run_bypasses_disabled_task_priority_oil_and_fault_cooldown(self):
        self.script.config.cross_set_many({'Research.Scheduler.Enable': True,
            'General.OilControl.Enable': True})
        self.script.task_restart_delays['Main'] = self.time + timedelta(days=1)
        self.script.task_restart_record['Main'] = 3
        self.script.failure_record = {'Main': 2, 'Research': 1}
        self.runtime.oil_control.select = Mock(side_effect=AssertionError('手动运行不能进入清油分流'))
        self.request()
        self.assertEqual(self.script.get_next_task(), 'Main')
        self.assertEqual(self.script.config.task.command, 'Main')
        self.assertNotIn('Main', self.script.task_restart_delays)
        self.assertNotIn('Main', self.script.task_restart_record)
        self.assertEqual(self.script.failure_record, {'Research': 1})
        self.assertIsNone(self.runtime.pending_manual_task())

    def test_manual_run_escapes_faulted_takeover_and_survives_automatic_deferral(self):
        self.apply(self.program(task='Research'))
        self.runtime.load_program()
        self.runtime.fault = '旧程序已停止'
        self.request()
        self.script.config.task_delay(target=self.time + timedelta(days=1), task='Main')
        self.assertEqual(self.runtime.next_task(), 'Main')
        self.assertEqual(self.runtime.pending_manual_task(), None)
        self.assertLess(self.script.config.cross_get('Main.Scheduler.NextRun'), self.time)

    def test_real_loop_runs_requested_task_without_waiting(self):
        self.script.task_restart_delays['Main'] = self.time + timedelta(days=1)
        self.request()
        self.script.main = Mock(side_effect=self.script.stop_event.set)
        self.script.loop()
        self.script.main.assert_called_once_with()

    def test_manual_request_yields_long_task_even_when_switching_is_disabled(self):
        self.script.config.task.command = 'Research'
        self.request()
        self.script.config.load()
        self.script.config._disable_task_switch = True
        with self.assertRaises(TaskEnd):
            self.script.config.check_task_switch()

    def test_repeated_click_is_a_new_request_and_migration_preserves_it(self):
        from module.config.config_updater import ConfigUpdater
        self.request()
        first = self.runtime.pending_manual_task()
        self.assertEqual(self.runtime.take_manual_task(), first)
        self.request()
        second = self.runtime.pending_manual_task()
        self.assertEqual(second, 'Main')
        data = json.loads(self.path.read_text(encoding='utf-8'))
        migrated = ConfigUpdater().config_update(data)
        self.assertEqual(migrated['General']['Storage']['Storage']['ManualTask'], second)

    def test_api_starts_stopped_scheduler_and_does_not_restart_running_worker(self):
        runtime = RuntimeService(ConfigService(self.root))
        manager = SimpleNamespace(alive=False)
        with patch.object(runtime, 'manager', return_value=manager), patch.object(runtime, 'start') as start:
            result = runtime.run_now('testpilot', 'Main')
            start.assert_called_once_with('testpilot')
            self.assertTrue(result['values']['Main']['Scheduler']['Enable'])
            manager.alive = True
            start.reset_mock()
            runtime.run_now('testpilot', 'Main')
            start.assert_not_called()

    def test_run_now_over_real_websocket_records_request(self):
        from starlette.testclient import TestClient
        from module.api.app import create_app
        app = create_app(root=self.root, password='', manage_runtime=False, mount_mcp=False)
        runtime = app.state.gateway.router.runtime
        with patch.object(runtime, 'manager', return_value=SimpleNamespace(alive=True)), \
                TestClient(app) as client, client.websocket_connect('/api/v1/ws') as ws:
            ws.receive_json()
            ws.send_json({'v': 1, 'type': 'request', 'id': 'manual', 'method': 'tasks.runNow',
                          'params': {'instance': 'testpilot', 'task': 'Main'}})
            reply = ws.receive_json()
            self.assertTrue(reply['ok'], reply)
            self.assertEqual(reply['result']['values']['General']['Storage']['Storage']['ManualTask'], 'Main')
        self.assertEqual(self.script.get_next_task(), 'Main')

    def test_pending_manual_request_wakes_wait_without_sleep(self):
        from alas import AzurLaneAutoScript
        self.request()
        with patch('alas.time.sleep') as sleep:
            self.assertFalse(AzurLaneAutoScript.wait_until(self.script, self.time + timedelta(hours=3)))
        sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
