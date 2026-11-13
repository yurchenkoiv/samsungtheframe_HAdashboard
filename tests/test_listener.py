import asyncio
import json
import unittest
from test_sensor import env

class ListenerTests(unittest.TestCase):
    def test_filter_art_mode_changed(self):
        parse = env.get('_is_art_mode_event')
        self.assertIsNotNone(parse, 'listener event filter not implemented')
        event = {'event': 'd2d_service_message', 'data': json.dumps({'event': 'art_mode_changed'})}
        self.assertTrue(parse(json.dumps(event)))
        for value in ('bad', '{}', json.dumps({'event': 'art_mode_changed'}), json.dumps({'event': 'd2d_service_message', 'data': '{'})):
            self.assertFalse(parse(value))

    def test_burst_debounce_and_removal_cancels(self):
        async def run():
            from types import SimpleNamespace
            entity = env['SamsungFrameArtModeSensor'](SimpleNamespace(entry_id='x', data={'tv_ip':'tv'}, options={}))
            entity.hass = SimpleNamespace(async_create_task=asyncio.create_task)
            updates = []
            entity.async_schedule_update_ha_state = lambda force: updates.append(force)
            entity._queue_event_refresh()
            entity._queue_event_refresh()
            await asyncio.sleep(.03)
            self.assertEqual(updates, [True])
            entity._queue_event_refresh()
            await entity.async_will_remove_from_hass()
            await asyncio.sleep(.03)
            self.assertEqual(updates, [True])
        env['asyncio'] = asyncio
        env['EVENT_DEBOUNCE'] = .01
        asyncio.run(run())

    def test_reconnect_after_disconnect_and_cancel_closes_socket(self):
        async def run():
            import base64
            from urllib.parse import urlencode
            from types import SimpleNamespace
            connections = []
            class WS:
                def __init__(self): self.closed = False
                async def __aenter__(self): connections.append(self); return self
                async def __aexit__(self, *args): self.closed = True
                def __aiter__(self): return self
                async def __anext__(self):
                    if len(connections) == 1: raise StopAsyncIteration
                    await asyncio.Event().wait()
            class Session:
                def ws_connect(self, url, **kwargs): return WS()
            async def executor(fn, *args): return 'token'
            env.update(asyncio=asyncio, base64=base64, urlencode=urlencode,
                       async_get_clientsession=lambda hass: Session(),
                       WSMsgType=SimpleNamespace(TEXT=1, ERROR=2, CLOSED=3))
            entity = env['SamsungFrameArtModeSensor'](SimpleNamespace(entry_id='x', data={'tv_ip':'tv'}, options={}))
            entity.hass = SimpleNamespace(async_create_task=asyncio.create_task, async_add_executor_job=executor,
                                          async_create_background_task=lambda coro, name: asyncio.create_task(coro))
            await entity.async_added_to_hass()
            await asyncio.sleep(2.1)
            self.assertEqual(len(connections), 2)
            self.assertTrue(connections[0].closed)
            await entity.async_will_remove_from_hass()
            self.assertTrue(connections[1].closed)
            self.assertTrue(entity._listener_task.done())
        asyncio.run(run())

    def test_listener_dispatches_only_matching_messages(self):
        async def run():
            import base64
            from urllib.parse import urlencode
            from types import SimpleNamespace
            typ = SimpleNamespace(TEXT=1, ERROR=2, CLOSED=3)
            class WS:
                async def __aenter__(self): return self
                async def __aexit__(self, *args): pass
                def __aiter__(self): return self
                async def __anext__(self):
                    if not hasattr(self, 'messages'):
                        self.messages = iter(['{}', json.dumps({'event':'d2d_service_message','data':json.dumps({'event':'art_mode_changed'})})])
                    value = next(self.messages, None)
                    if value is None: await asyncio.Event().wait()
                    return SimpleNamespace(type=1, data=value)
            class Session:
                def ws_connect(self, *args, **kwargs): return WS()
            async def executor(fn, *args): return ''
            env.update(asyncio=asyncio, base64=base64, urlencode=urlencode, WSMsgType=typ,
                       async_get_clientsession=lambda hass: Session(), EVENT_DEBOUNCE=.01)
            entity = env['SamsungFrameArtModeSensor'](SimpleNamespace(entry_id='x',data={'tv_ip':'tv'},options={}))
            entity.hass = SimpleNamespace(async_create_task=asyncio.create_task, async_add_executor_job=executor,
                                          async_create_background_task=lambda coro, name: asyncio.create_task(coro))
            updates = []
            entity.async_schedule_update_ha_state = lambda force: updates.append(force)
            await entity.async_added_to_hass()
            await asyncio.sleep(.05)
            self.assertEqual(updates, [True])
            await entity.async_will_remove_from_hass()
        asyncio.run(run())
