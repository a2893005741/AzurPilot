"""故障记录的只读隔离、边界与真实 WebSocket 认证测试。"""
import base64
import io
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from starlette.testclient import TestClient

from module.api.app import create_app
from module.api.config_service import ConfigService
from module.api.error_service import ErrorService, FILE_LIMIT, LOG_LIMIT
from module.api.protocol import ApiError
from tests.test_api import fixture

IMAGE = '2026-10-21_12-30-00-123456.png'
RECORD = '1792540800000'


class ErrorRecordsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = fixture(self.temp.name)
        self.configs = ConfigService(self.root)
        self.service = ErrorService(self.configs)
        self.folder = self.root / 'log/error/testpilot' / RECORD
        self.folder.mkdir(parents=True)
        (self.folder / 'log.txt').write_text('错误：测试现场\nTraceback\n', encoding='utf-8')
        Image.new('RGB', (1280, 720), '#233849').save(self.folder / IMAGE)

    def test_list_sorted_paged_and_instance_scoped(self):
        (self.folder.parent / '1792540800001').mkdir()
        (self.folder.parent / 'bak').mkdir()
        (self.root / 'log/error/other/1792540800002').mkdir(parents=True)
        result = self.service.list('testpilot', limit=1)
        self.assertEqual(result['total'], 2)
        self.assertTrue(result['enabled'])
        self.assertEqual(result['entries'][0]['id'], '1792540800001')
        entry = self.service.list('testpilot', offset=1)['entries'][0]
        self.assertEqual(entry, dict(id=RECORD, timestamp=int(RECORD), screenshots=1, has_log=True))

    def test_detail_and_full_file(self):
        detail = self.service.detail('testpilot', RECORD)
        self.assertEqual(detail['images'], [IMAGE])
        self.assertIn('测试现场', detail['log'])
        self.assertFalse(detail['truncated'])
        for name in ('log.txt', IMAGE):
            result = self.service.file('testpilot', RECORD, name)
            self.assertEqual(base64.b64decode(result['content']), (self.folder / name).read_bytes())
            if name == IMAGE:
                self.assertEqual(result['media_type'], 'image/png')
                with Image.open(io.BytesIO(base64.b64decode(result['content']))) as image:
                    self.assertEqual(image.size, (1280, 720))
                    image.verify()

    def test_large_log_is_bounded_and_full_download_is_preserved(self):
        content = '首部\n' + 'x' * LOG_LIMIT + '\n末尾错误'
        (self.folder / 'log.txt').write_text(content, encoding='utf-8')
        detail = self.service.detail('testpilot', RECORD)
        self.assertTrue(detail['truncated'])
        self.assertTrue(detail['log'].endswith('末尾错误'))
        self.assertLessEqual(len(detail['log']), LOG_LIMIT)
        download = self.service.file('testpilot', RECORD, 'log.txt')
        self.assertEqual(base64.b64decode(download['content']), (self.folder / 'log.txt').read_bytes())

    def test_missing_log_and_screenshots_remain_visible(self):
        (self.folder / 'log.txt').unlink()
        self.assertIsNone(self.service.detail('testpilot', RECORD)['log'])
        self.assertFalse(self.service.list('testpilot')['entries'][0]['has_log'])
        (self.folder / IMAGE).unlink()
        self.assertEqual(self.service.detail('testpilot', RECORD)['images'], [])

    def test_missing_directory_and_disabled_save(self):
        import json
        import shutil
        shutil.rmtree(self.root / 'log')
        data = self.configs.read_json(self.configs.path('testpilot'))
        data['Alas']['Error']['SaveError'] = False
        self.configs.path('testpilot').write_text(json.dumps(data), encoding='utf-8')
        result = self.service.list('testpilot')
        self.assertEqual(result['entries'], [])
        self.assertFalse(result['enabled'])

    def test_missing_record_and_file_are_not_found(self):
        for operation in (lambda: self.service.detail('testpilot', '1792540800001'),
                          lambda: self.service.file('testpilot', RECORD, '2026-10-21_12-30-00-999999.png')):
            with self.assertRaises(ApiError) as caught:
                operation()
            self.assertEqual(caught.exception.code, 'NOT_FOUND')

    def test_paths_and_non_evidence_files_are_rejected(self):
        for name in ('../log.txt', '..\\log.txt', 'C:\\secret.png', 'config.json', 'image.svg'):
            with self.subTest(name=name), self.assertRaises(ApiError):
                self.service.file('testpilot', RECORD, name)
        for record in ('../testpilot', 'bak', '99999999999999999999'):
            with self.subTest(record=record), self.assertRaises(ApiError):
                self.service.detail('testpilot', record)
        with self.assertRaises(ApiError):
            self.service.list('../testpilot')
        with self.assertRaises(ApiError):
            self.service.list('unknown')

    def test_symlink_file_and_record_are_rejected(self):
        external = self.root / 'private.txt'
        external.write_text('secret', encoding='utf-8')
        log = self.folder / 'log.txt'
        log.unlink()
        log.symlink_to(external)
        with self.assertRaises(ApiError):
            self.service.file('testpilot', RECORD, 'log.txt')
        linked = self.folder.parent / '1792540800001'
        linked.symlink_to(self.folder, target_is_directory=True)
        with self.assertRaises(ApiError):
            self.service.detail('testpilot', linked.name)

    def test_oversized_file_is_rejected(self):
        with (self.folder / IMAGE).open('wb') as stream:
            stream.truncate(FILE_LIMIT + 1)
        with self.assertRaises(ApiError) as caught:
            self.service.file('testpilot', RECORD, IMAGE)
        self.assertIn('8 MiB', caught.exception.message)

    def test_cleanup_during_read_is_reported(self):
        with patch.object(self.service, 'images', side_effect=FileNotFoundError):
            self.assertEqual(self.service.list('testpilot')['entries'], [])
            with self.assertRaises(ApiError) as caught:
                self.service.detail('testpilot', RECORD)
            self.assertEqual(caught.exception.code, 'NOT_FOUND')

    def test_queries_preserve_config_and_evidence(self):
        paths = [self.configs.path('testpilot'), self.folder / 'log.txt', self.folder / IMAGE]
        before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
        self.service.list('testpilot')
        self.service.detail('testpilot', RECORD)
        self.service.file('testpilot', RECORD, IMAGE)
        self.assertEqual(before, [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths])

    def test_websocket_requires_login_and_validates_params(self):
        application = create_app(root=self.root, password='test-secret', manage_runtime=False, mount_mcp=False)
        with TestClient(application) as client, client.websocket_connect('/api/v1/ws') as ws:
            ws.receive_json()
            counter = 0

            def call(method, params):
                nonlocal counter
                counter += 1
                ws.send_json(dict(v=1, type='request', id=str(counter), method=method, params=params))
                while True:
                    result = ws.receive_json()
                    if result.get('id') == str(counter):
                        return result

            for method in ('errors.list', 'errors.detail', 'errors.file'):
                self.assertEqual(call(method, {})['error']['code'], 'UNAUTHORIZED')
            self.assertTrue(call('auth.login', dict(password='test-secret'))['ok'])
            self.assertEqual(call('errors.list', dict(instance='testpilot', limit=101))['error']['code'], 'INVALID_PARAMS')
            self.assertEqual(call('errors.list', dict(instance='testpilot', offset=-1))['error']['code'], 'INVALID_PARAMS')
            self.assertEqual(call('errors.detail', dict(instance='testpilot', record='../'))['error']['code'], 'INVALID_PARAMS')
            result = call('errors.list', dict(instance='testpilot'))
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['result']['entries'][0]['id'], RECORD)
            self.assertTrue(call('errors.detail', dict(instance='testpilot', record=RECORD))['ok'])
            self.assertTrue(call('errors.file', dict(instance='testpilot', record=RECORD, name=IMAGE))['ok'])
            self.assertEqual(call('errors.file', dict(instance='testpilot', record=RECORD, name='../private.txt'))['error']['code'], 'INVALID_PARAMS')
            # 没有公开的错误目录静态挂载。
            self.assertNotIn('测试现场', client.get(f'/log/error/testpilot/{RECORD}/log.txt').text)


if __name__ == '__main__':
    unittest.main()
