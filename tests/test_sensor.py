import ast
import asyncio
import json
import logging
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1] / 'custom_components/samsung_frame'
init = ast.parse((ROOT / '__init__.py').read_text())
selected = [n for n in init.body if isinstance(n, ast.FunctionDef) and n.name in ('_send_art_request', '_read_art_mode_on_connection')]
import uuid
ns = {'json': json, 'uuid': uuid}
exec(compile(ast.Module(body=selected, type_ignores=[]), '<init>', 'exec'), ns)

class Socket:
    def __init__(self, value): self.value, self.sent, self.closed = value, [], False
    def settimeout(self, value): pass
    def send(self, data): self.sent.append(json.loads(data))
    def recv(self):
        if isinstance(self.value, Exception): raise self.value
        return json.dumps({'event': 'd2d_service_message', 'data': json.dumps({'event': 'artmode_status', 'value': self.value})})
    def close(self): self.closed = True

sensor_tree = ast.parse((ROOT / 'sensor.py').read_text())
nodes = [n for n in sensor_tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
class SensorEntity:
    async def async_added_to_hass(self): pass
    async def async_will_remove_from_hass(self): pass
env = {'__builtins__': __builtins__, 'json': json, 'SensorEntity': SensorEntity, 'ConfigEntry': object,
       'HomeAssistant': object, 'AddEntitiesCallback': object, 'DOMAIN': 'samsung_frame',
       'CONF_TV_IP': 'tv_ip', 'CONF_TOKEN_FILE': 'token_file', 'DEFAULT_TOKEN_FILE': 'default',
       '_LOGGER': logging.getLogger('test'), '_read_art_mode_on_connection': ns['_read_art_mode_on_connection']}
exec(compile(ast.Module(body=nodes, type_ignores=[]), '<sensor>', 'exec'), env)

class Tests(unittest.TestCase):
    def test_values_and_only_status_request(self):
        for value, expected in [('on', 'on'), ('off', 'off'), ('unknown', None), (TimeoutError(), None)]:
            conn = Socket(value)
            connect = Mock(return_value=conn); env['_art_connect'] = connect
            self.assertEqual(env['_read_status']('tv', 'token'), expected)
            self.assertTrue(conn.closed)
            connect.assert_called_once_with('tv', 'token', persist_token=False)
            self.assertEqual([json.loads(x['params']['data'])['request'] for x in conn.sent], ['get_artmode_status'])
    def test_connection_error(self):
        env['_art_connect'] = Mock(side_effect=OSError('offline'))
        self.assertIsNone(env['_read_status']('tv', 'token'))
    def test_entity_executor_and_device(self):
        entry = SimpleNamespace(entry_id='abc', data={'tv_ip': 'tv'}, options={})
        entity = env['SamsungFrameArtModeSensor'](entry)
        async def executor(fn, *args):
            self.assertEqual(args, ('tv', 'default'))
            return 'off'
        entity.hass = SimpleNamespace(async_add_executor_job=executor)
        asyncio.run(entity.async_update())
        self.assertEqual(entity._attr_native_value, 'off')
        self.assertEqual(entity._attr_device_info['identifiers'], {('samsung_frame', 'abc')})
        self.assertEqual(entity._attr_unique_id, 'abc_art_mode_status')

if __name__ == '__main__': unittest.main()
