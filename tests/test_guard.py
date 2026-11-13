import ast
import asyncio
import json
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock

source = (Path(__file__).resolve().parents[1] / 'custom_components/samsung_frame/__init__.py').read_text()
tree = ast.parse(source)
nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('_read_art_mode_on_connection', '_require_art_mode_on_connection', '_require_art_mode')]
ns = {'json': json, 'uuid': uuid}
exec(compile(ast.Module(body=nodes, type_ignores=[]), '<integration>', 'exec'), ns)

class Socket:
    def __init__(self, messages): self.messages = iter(messages); self.closed = False
    def settimeout(self, timeout): pass
    def recv(self):
        value = next(self.messages)
        if isinstance(value, Exception): raise value
        return json.dumps(value)
    def close(self): self.closed = True

def event(value): return {'event':'d2d_service_message', 'data':json.dumps({'event':'artmode_status', 'value':value})}

class Tests(unittest.TestCase):
    def setUp(self):
        self.sent=[]
        ns['_send_art_request'] = lambda conn, data: self.sent.append(data)
    def check(self, messages): ns['_require_art_mode_on_connection'](Socket(messages))
    def test_on(self):
        self.check([event('on')]); self.assertEqual(self.sent[0]['request'], 'get_artmode_status')
    def test_off(self):
        with self.assertRaisesRegex(RuntimeError, 'not on'): self.check([event('off')])
    def test_unknown(self):
        with self.assertRaises(RuntimeError): self.check([event('unknown')])
    def test_timeout(self):
        with self.assertRaises(TimeoutError): self.check([TimeoutError('timeout')])
    def test_unrelated_and_malformed_then_on(self):
        self.check([{'event':'irrelevant'}, {'event':'d2d_service_message','data':'{'}, event('on')])
    def test_mismatch_not_accepted(self):
        wrong={'event':'d2d_service_message','data':json.dumps({'event':'artmode_status','value':'on','request_id':'other'})}
        with self.assertRaises(TimeoutError): self.check([wrong, TimeoutError()])
    def test_connection_always_closed(self):
        conn=Socket([event('off')]); ns['_art_connect']=lambda *a: conn
        with self.assertRaises(RuntimeError): ns['_require_art_mode']('tv','token')
        self.assertTrue(conn.closed)
    def test_guards_at_selection_and_upload_and_display(self):
        setup=next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name=='async_setup_entry')
        handler=next(n for n in setup.body if isinstance(n, ast.AsyncFunctionDef) and n.name=='handle_update')
        text=ast.get_source_segment(source,handler)
        self.assertLess(text.index('async_add_executor_job(_require_art_mode'),text.index('random.choice(images)'))
        push=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_push_to_tv')
        text=ast.get_source_segment(source,push)
        self.assertLess(text.index('_require_art_mode_on_connection(conn)'),text.index('send_image'))
        self.assertLess(text.rindex('_require_art_mode_on_connection(conn)'),text.index('build_select_request(content_id'))
        self.assertIn('raise RuntimeError(f"Failed to push image to TV:', ast.get_source_segment(source,handler))

class PushTests(unittest.TestCase):
    def test_off_before_upload_and_before_select(self):
        import sys, types, logging
        from unittest.mock import patch
        protocol=types.ModuleType('fakepackage.art_protocol')
        protocol.build_d2d_header=lambda *a: b''
        protocol.build_select_request=lambda content, request_id: {'request':'select_image'}
        protocol.upload_mode_for_api=lambda version: 'websocket_binary'
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_push_to_tv')
        env={'__package__':'fakepackage','uuid':uuid,'json':json,'_LOGGER':logging.getLogger('test')}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<integration>','exec'),env)
        for guard_calls in (1, 2):
            with self.subTest(guard_calls=guard_calls):
                conn=Mock(); conn.send_binary=Mock(); env['_art_connect']=lambda *a: conn
                calls=[]
                def guard(c):
                    calls.append('guard')
                    if len(calls)==guard_calls: raise RuntimeError('off')
                env['_require_art_mode_on_connection']=guard
                sent=[]; env['_send_art_request']=lambda c, d: sent.append(d)
                replies=iter([{'event':'api_version','version':'1'}, {'event':'image_added','content_id':'MY_1'}])
                env['_recv_until']=lambda *a, **kw: next(replies)
                with patch.dict(sys.modules, {'fakepackage.art_protocol':protocol}):
                    with self.assertRaisesRegex(RuntimeError,'off'): env['_push_to_tv']('tv','token',b'image','none')
                self.assertEqual(conn.send_binary.called, guard_calls==2)
                self.assertFalse(any(x['request']=='select_image' for x in sent))
                conn.close.assert_called_once()

if __name__=='__main__': unittest.main()
