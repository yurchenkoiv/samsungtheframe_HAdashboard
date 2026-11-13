"""Read-only Samsung Frame Art Mode status."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from urllib.parse import urlencode

from aiohttp import WSMsgType
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from datetime import timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import _art_connect, _read_art_mode_on_connection
from .const import CONF_TOKEN_FILE, CONF_TV_IP, DEFAULT_TOKEN_FILE, DOMAIN

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(minutes=5)
EVENT_DEBOUNCE = 1.0


def _read_token(token_file: str) -> str:
    try:
        with open(token_file, encoding="utf-8") as token:
            return token.readline().strip()
    except OSError:
        return ""


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([SamsungFrameArtModeSensor(entry)])


def _is_art_mode_event(raw: str) -> bool:
    try:
        message = json.loads(raw)
        if not isinstance(message, dict) or message.get("event") != "d2d_service_message":
            return False
        data = message.get("data")
        if isinstance(data, str):
            data = json.loads(data)
        return isinstance(data, dict) and data.get("event") == "art_mode_changed"
    except (ValueError, TypeError):
        return False


def _read_status(tv_ip: str, token_file: str) -> str | None:
    """Only query status; no select, power, or token-file writes."""
    conn = None
    try:
        conn = _art_connect(tv_ip, token_file, persist_token=False)
        return _read_art_mode_on_connection(conn)
    except Exception as err:
        _LOGGER.debug("Unable to read Frame Art Mode status: %s", err)
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                _LOGGER.debug("Error closing Art Mode connection", exc_info=True)


class SamsungFrameArtModeSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Art Mode Status"
    _attr_icon = "mdi:image-frame"
    _attr_native_value = None

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._listener_task = None
        self._refresh_task = None
        self._removed = False
        self._attr_unique_id = f"{entry.entry_id}_art_mode_status"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"Samsung Frame ({entry.data.get('tv_ip', '')})",
        }

    def _queue_event_refresh(self) -> None:
        if self._removed or (self._refresh_task and not self._refresh_task.done()):
            return
        self._refresh_task = self.hass.async_create_task(self._debounced_refresh())

    async def _debounced_refresh(self) -> None:
        await asyncio.sleep(EVENT_DEBOUNCE)
        if not self._removed:
            self.async_schedule_update_ha_state(True)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._listener_task = self.hass.async_create_background_task(
            self._listen(), "samsung_frame_art_mode_listener")

    async def async_will_remove_from_hass(self) -> None:
        self._removed = True
        tasks = [task for task in (self._listener_task, self._refresh_task) if task]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await super().async_will_remove_from_hass()

    async def _listen(self) -> None:
        delay = 2
        while True:
            started = asyncio.get_running_loop().time()
            try:
                config = {**self._entry.data, **self._entry.options}
                token = await self.hass.async_add_executor_job(
                    _read_token, config.get(CONF_TOKEN_FILE, DEFAULT_TOKEN_FILE))
                params = {"name": base64.b64encode(b"SamsungTvRemote").decode("ascii")}
                if token:
                    params["token"] = token
                url = f"wss://{config[CONF_TV_IP]}:8002/api/v2/channels/com.samsung.art-app?{urlencode(params)}"
                session = async_get_clientsession(self.hass)
                async with session.ws_connect(url, ssl=False, heartbeat=30, timeout=10) as ws:
                    async for msg in ws:
                        if msg.type == WSMsgType.TEXT and _is_art_mode_event(msg.data):
                            self._queue_event_refresh()
                        elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSED):
                            break
            except asyncio.CancelledError:
                raise
            except Exception as err:
                _LOGGER.debug("Frame Art event listener disconnected: %s", type(err).__name__)
            if asyncio.get_running_loop().time() - started >= 60:
                delay = 2
            await asyncio.sleep(delay)
            delay = min(delay * 2, 300)

    async def async_update(self) -> None:
        config = {**self._entry.data, **self._entry.options}
        self._attr_native_value = await self.hass.async_add_executor_job(
            _read_status, config[CONF_TV_IP], config.get(CONF_TOKEN_FILE, DEFAULT_TOKEN_FILE)
        )
