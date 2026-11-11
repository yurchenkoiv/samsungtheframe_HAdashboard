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


if __name__ == '__main__':
    unittest.main()
