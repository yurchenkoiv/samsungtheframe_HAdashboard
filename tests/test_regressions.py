"""Dependency-free protocol and lifecycle regression tests."""
import ast
import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / 'custom_components' / 'samsung_frame'
spec = importlib.util.spec_from_file_location('art_protocol', COMPONENT / 'art_protocol.py')
assert spec is not None and spec.loader is not None
protocol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(protocol)


class RegressionTests(unittest.TestCase):
    def test_legacy_transport(self):
        self.assertEqual(protocol.upload_mode_for_api('0.97'), 'websocket_binary')

    def test_api2_transport(self):
        self.assertEqual(protocol.upload_mode_for_api('2.03'), 'd2d_socket')

    def test_unknown_transport(self):
        for value in (None, '', 'unknown'):
            self.assertEqual(protocol.upload_mode_for_api(value), 'websocket_binary')

    def test_d2d_header(self):
        data = protocol.build_d2d_header(1234, 'JPEG', 'test-key')
        self.assertEqual(int.from_bytes(data[:4], 'big'), len(data[4:]))
        header = json.loads(data[4:])
        self.assertEqual(header['fileLength'], 1234)
        self.assertEqual(header['secKey'], 'test-key')
        self.assertEqual(header['fileType'], 'JPEG')

    def test_select_request(self):
        request = protocol.build_select_request('test-content', 'test-request')
        self.assertEqual(request['id'], 'test-request')
        self.assertEqual(request['request_id'], 'test-request')
        self.assertEqual(request['content_id'], 'test-content')
        self.assertIs(request['show'], True)

    def test_managed_reload(self):
        tree = ast.parse((COMPONENT / '__init__.py').read_text())
        callback = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'async_reload_entry')
        for arg in callback.args.args:
            arg.annotation = None
        callback.returns = None
        namespace = {}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[callback], type_ignores=[])), '<callback>', 'exec'), namespace)
        reload = AsyncMock()
        hass = SimpleNamespace(config_entries=SimpleNamespace(async_reload=reload))
        asyncio.run(namespace['async_reload_entry'](hass, SimpleNamespace(entry_id='test-entry')))
        reload.assert_awaited_once_with('test-entry')

    def test_options_flow_does_not_assign_config_entry(self):
        tree = ast.parse((COMPONENT / 'config_flow.py').read_text())
        flow = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'SamsungFrameOptionsFlow')
        for node in ast.walk(flow):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    self.assertFalse(isinstance(target, ast.Attribute) and target.attr == 'config_entry')


class DeleteRegressionTests(unittest.TestCase):
    def run_delete(self, conn):
        import logging
        import sys
        tree = ast.parse((COMPONENT / '__init__.py').read_text())
        nodes: list[ast.stmt] = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name in ('_delete_all_tv_images', '_send_art_request')]
        sys.modules['regression_component.art_protocol'] = protocol
        namespace = {'__package__': 'regression_component', 'json': json,
                     '_LOGGER': logging.getLogger(__name__),
                     '_art_connect': lambda *args: conn}
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                     '<actual deletion functions>', 'exec'), namespace)
        return namespace['_delete_all_tv_images']('fake-tv', 'unused-token')

    def test_api2_deletes_only_uploads_and_verifies(self):
        conn = FakeArtSocket(event='get_content_list')
        self.assertEqual(self.run_delete(conn), 1)
        self.assertEqual(conn.deleted, ['MY_F0001'])
        self.assertGreaterEqual(conn.lists, 2)
        self.assertTrue(conn.closed)


    def test_service_propagates_deletion_failure(self):
        tree = ast.parse((COMPONENT / '__init__.py').read_text())
        handler = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)
                       and n.name == 'handle_delete_all_images')
        for arg in handler.args.args:
            arg.annotation = None
        handler.returns = None
        import logging
        namespace = {'entry': SimpleNamespace(data={'tv': 'fake'}, options={}),
                     'CONF_TV_IP': 'tv', 'CONF_TOKEN_FILE': 'token',
                     '_LOGGER': logging.getLogger(__name__),
                     '_delete_all_tv_images': object(),
                     'hass': SimpleNamespace(async_add_executor_job=AsyncMock(
                         side_effect=RuntimeError('Deletion not confirmed')))}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[handler], type_ignores=[])),
                     '<actual service handler>', 'exec'), namespace)
        with self.assertLogs(__name__, level='ERROR'):
            with self.assertRaisesRegex(RuntimeError, 'not confirmed'):
                asyncio.run(namespace['handle_delete_all_images'](None))

    def test_delete_reply_event_name_is_not_assumed(self):
        conn = FakeArtSocket(fail='legacy_delete_event')
        self.assertEqual(self.run_delete(conn), 1)

    def test_legacy_content_list_event(self):
        self.assertEqual(self.run_delete(FakeArtSocket()), 1)

    def test_acknowledged_but_unchanged_raises(self):
        conn = FakeArtSocket(unchanged=True)
        with self.assertRaisesRegex(RuntimeError, 'remain'):
            self.run_delete(conn)
        self.assertEqual(conn.lists, 4)
        self.assertTrue(conn.closed)

    def test_no_response_is_not_empty_success(self):
        conn = FakeArtSocket(fail='timeout')
        with self.assertRaisesRegex(RuntimeError, 'confirmation'):
            self.run_delete(conn)
        self.assertEqual(conn.deleted, [])
        self.assertTrue(conn.closed)

    def test_tv_error_raises(self):
        conn = FakeArtSocket(fail='error')
        with self.assertRaisesRegex(RuntimeError, 'rejected'):
            self.run_delete(conn)
        self.assertTrue(conn.closed)

    def test_mismatched_delete_ack_raises(self):
        conn = FakeArtSocket(fail='bad_ack')
        with self.assertRaisesRegex(RuntimeError, 'confirm'):
            self.run_delete(conn)
        self.assertTrue(conn.closed)

    def test_foreign_response_is_ignored(self):
        conn = FakeArtSocket(fail='foreign')
        self.assertEqual(self.run_delete(conn), 1)
        self.assertEqual(conn.deleted, ['MY_F0001'])

    def test_empty_uploads_does_not_delete_store_art(self):
        conn = FakeArtSocket()
        conn.items = [conn.items[1], {'content_id': 'MY_bad', 'content_type': 'preinstall'}]
        self.assertEqual(self.run_delete(conn), 0)
        self.assertEqual(conn.deleted, [])

    def test_malformed_list_never_deletes(self):
        conn = FakeArtSocket()
        conn.items = [{'id': 'MY_F0001'}]
        with self.assertRaisesRegex(RuntimeError, 'invalid content list'):
            self.run_delete(conn)
        self.assertEqual(conn.deleted, [])


class FakeArtSocket:
    def __init__(self, event='content_list', unchanged=False, fail=None):
        self.event, self.unchanged, self.fail = event, unchanged, fail
        self.closed = False
        self.deleted = []
        self.queue = []
        self.lists = 0
        self.items = [{'content_id': 'MY_F0001', 'category_id': 'M0002', 'content_type': 'usb'},
                      {'content_id': 'SAM-S0001', 'category_id': 'M0002', 'content_type': 'server'}]

    def settimeout(self, value):
        pass

    def send(self, raw):
        data = json.loads(json.loads(raw)['params']['data'])
        rid = data.get('request_id', data.get('id'))
        if data['request'] == 'get_content_list':
            self.lists += 1
            items = self.items if data.get('category') is None else []
            reply = {'event': self.event, 'id': rid, 'content_list': json.dumps(items)}
        else:
            ids = [item['content_id'] for item in data['content_id_list']]
            self.deleted.extend(ids)
            if not self.unchanged:
                self.items = [item for item in self.items if item['content_id'] not in ids]
            reply = {'event': 'delete_image_list', 'request_id': rid,
                     'content_id_list': json.dumps(data['content_id_list'])}
        if self.fail == 'legacy_delete_event' and data['request'] == 'delete_image_list':
            reply['event'] = 'firmware_specific_delete_reply'
        if self.fail == 'timeout':
            return
        if self.fail == 'error':
            reply = {'event': 'error', 'request_id': rid, 'error_code': 'test-rejection'}
        if self.fail == 'bad_ack' and data['request'] == 'delete_image_list':
            reply['content_id_list'] = '[]'
        if self.fail == 'foreign':
            foreign = {'event': 'content_list', 'id': 'other-request',
                       'content_list': '[{"content_id": "MY_FOREIGN"}]'}
            self.queue.append(json.dumps({'event': 'd2d_service_message', 'data': foreign}))
        self.queue.append(json.dumps({'event': 'd2d_service_message', 'data': json.dumps(reply)}))

    def recv(self):
        if not self.queue:
            raise TimeoutError('fake timeout')
        return self.queue.pop(0)

    def close(self):
        self.closed = True


if __name__ == '__main__':
    unittest.main()
