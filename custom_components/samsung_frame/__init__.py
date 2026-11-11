"""Samsung Frame Art custom integration."""
from __future__ import annotations

import logging
import os
import random
import json
import ssl
import socket
import uuid
import base64
from datetime import date, datetime, timedelta

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_TV_IP,
    CONF_MEDIA_FOLDER,
    CONF_TOKEN_FILE,
    CONF_CALENDAR_ENTITY,
    CONF_LANGUAGE,
    CONF_UPCOMING_DAYS,
    CONF_MATTE_COLOR,
    CONF_OVERLAY_OPACITY,
    CONF_DEBUG_SAVE,
    CONF_FONT_SIZE,
    DEFAULT_UPCOMING_DAYS,
    DEFAULT_MATTE_COLOR,
    DEFAULT_LANGUAGE,
    DEFAULT_OVERLAY_OPACITY,
    DEFAULT_DEBUG_SAVE,
    DEFAULT_FONT_SIZE,
    SERVICE_UPDATE,
)
from .overlay import compose_overlay

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["button", "image", "number", "select", "switch", "text"]

SERVICE_UPDATE_SCHEMA = vol.Schema({
    vol.Optional("image_path"): cv.string,
})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Samsung Frame Art from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def handle_update(call: ServiceCall) -> None:
        config = {**entry.data, **entry.options}

        tv_ip           = config[CONF_TV_IP]
        media_folder    = config[CONF_MEDIA_FOLDER]
        token_file      = config.get(CONF_TOKEN_FILE, "/config/samsung_frame_token.txt")
        calendar_entity = config.get(CONF_CALENDAR_ENTITY, "")
        lang            = config.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
        upcoming_days   = int(config.get(CONF_UPCOMING_DAYS, DEFAULT_UPCOMING_DAYS))
        matte           = config.get(CONF_MATTE_COLOR, DEFAULT_MATTE_COLOR)
        opacity = int(config.get(CONF_OVERLAY_OPACITY, DEFAULT_OVERLAY_OPACITY))  # temporary, overridden below
        image_path      = call.data.get("image_path")

        # Read font_size and debug_save from HA entity states
        ent_reg = er.async_get(hass)

        def _state_by_unique_id(unique_id):
            entry_obj = ent_reg.async_get_entity_id_from_unique_id(unique_id) if hasattr(ent_reg, "async_get_entity_id_from_unique_id") else None
            if entry_obj is None:
                # fallback: scan registry
                for e in ent_reg.entities.values():
                    if e.unique_id == unique_id:
                        return hass.states.get(e.entity_id)
            else:
                return hass.states.get(entry_obj)
            return None

        fs_state = _state_by_unique_id(f"{entry.entry_id}_font_size")
        font_size = int(float(fs_state.state)) if fs_state and fs_state.state not in ("unknown", "unavailable") else DEFAULT_FONT_SIZE

        ds_state = _state_by_unique_id(f"{entry.entry_id}_debug_save")
        debug_save = (ds_state.state == "on") if ds_state and ds_state.state not in ("unknown", "unavailable") else False

        show_date_state = _state_by_unique_id(f"{entry.entry_id}_show_date")
        show_date = (show_date_state.state != "off") if show_date_state and show_date_state.state not in ("unknown", "unavailable") else True

        show_cal_state = _state_by_unique_id(f"{entry.entry_id}_show_calendar")
        show_calendar = (show_cal_state.state != "off") if show_cal_state and show_cal_state.state not in ("unknown", "unavailable") else True

        lang_state = _state_by_unique_id(f"{entry.entry_id}_language")
        if lang_state and lang_state.state not in ("unknown", "unavailable"):
            from .const import LANGUAGES as _LANGS
            lang = next((k for k, v in _LANGS.items() if v == lang_state.state), lang)

        brightness_state = _state_by_unique_id(f"{entry.entry_id}_brightness")
        brightness = int(float(brightness_state.state)) if brightness_state and brightness_state.state not in ("unknown", "unavailable") else 50

        opacity_state = _state_by_unique_id(f"{entry.entry_id}_opacity")
        opacity = int(float(opacity_state.state)) if opacity_state and opacity_state.state not in ("unknown", "unavailable") else int(config.get(CONF_OVERLAY_OPACITY, DEFAULT_OVERLAY_OPACITY))

        # Folder path entity override
        folder_state = _state_by_unique_id(f"{entry.entry_id}_folder_path")
        if folder_state and folder_state.state not in ("unknown", "unavailable", ""):
            media_folder = folder_state.state.strip() or media_folder

        # Days to show entity override
        days_state = _state_by_unique_id(f"{entry.entry_id}_days_to_show")
        if days_state and days_state.state not in ("unknown", "unavailable"):
            try:
                upcoming_days = int(float(days_state.state))
            except ValueError:
                pass

        # Digital matte type and color
        matte_type_state = _state_by_unique_id(f"{entry.entry_id}_matte_type")
        matte_type = matte_type_state.state if matte_type_state and matte_type_state.state not in ("unknown", "unavailable") else "none"

        matte_color_state = _state_by_unique_id(f"{entry.entry_id}_matte_color")
        matte_color = matte_color_state.state.strip() if matte_color_state and matte_color_state.state not in ("unknown", "unavailable") else "#F5F0E8"

        # File name entity override
        fname_state = _state_by_unique_id(f"{entry.entry_id}_file_name")
        fname = fname_state.state.strip() if fname_state and fname_state.state not in ("unknown", "unavailable") else ""

        # Weather entity
        show_weather_state = _state_by_unique_id(f"{entry.entry_id}_show_weather")
        show_weather = (show_weather_state.state != "off") if show_weather_state and show_weather_state.state not in ("unknown", "unavailable") else True

        weather_ent_state = _state_by_unique_id(f"{entry.entry_id}_weather_entity")
        weather_entity = weather_ent_state.state.strip() if weather_ent_state and weather_ent_state.state not in ("unknown", "unavailable", "none", "") else ""

        _LOGGER.info("font_size=%s opacity=%s show_date=%s show_calendar=%s show_weather=%s days=%s folder=%s file=%s",
                     font_size, opacity, show_date, show_calendar, show_weather, upcoming_days, media_folder, fname or "random")

        # ── Resolve image path ────────────────────────────────────────────────
        if not image_path:
            if fname:
                # Use specified file (relative to folder or absolute)
                if os.path.isabs(fname):
                    image_path = fname
                else:
                    image_path = os.path.join(media_folder, fname)
                if not os.path.exists(image_path):
                    _LOGGER.error("Specified file not found: %s", image_path)
                    return
            else:
                def _list_images(folder):
                    if not os.path.isdir(folder):
                        return []
                    return [
                        os.path.join(folder, f)
                        for f in os.listdir(folder)
                        if f.lower().endswith((".jpg", ".jpeg", ".png"))
                        and not f.startswith("frame_")
                    ]
                images = await hass.async_add_executor_job(_list_images, media_folder)
                if not images:
                    _LOGGER.error("No images found in %s", media_folder)
                    return
                image_path = random.choice(images)
            _LOGGER.info("Selected image: %s", image_path)

        # ── Pick a random image ───────────────────────────────────────────────
        if not image_path:
            def _list_images(folder):
                if not os.path.isdir(folder):
                    return []
                return [
                    os.path.join(folder, f)
                    for f in os.listdir(folder)
                    if f.lower().endswith((".jpg", ".jpeg", ".png"))
                    and not f.startswith("frame_")  # skip debug saves
                ]
            images = await hass.async_add_executor_job(_list_images, media_folder)
            if not images:
                _LOGGER.error("No images found in %s", media_folder)
                return
            image_path = random.choice(images)
            _LOGGER.info("Selected image: %s", image_path)

        # ── Fetch calendar events ─────────────────────────────────────────────
        events = []
        if calendar_entity:
            try:
                now = dt_util.now()
                # days=1 = today only, days=2 = today+tomorrow, etc.
                end = dt_util.start_of_local_day(now) + timedelta(days=upcoming_days)
                calendar_events = await hass.services.async_call(
                    "calendar", "get_events",
                    {
                        "entity_id": calendar_entity,
                        "start_date_time": now.isoformat(),
                        "end_date_time": end.isoformat(),
                    },
                    blocking=True,
                    return_response=True,
                )
                raw = (calendar_events or {}).get(calendar_entity, {}).get("events", [])
                for ev in raw:
                    start = ev.get("start")
                    end_dt = ev.get("end")
                    if isinstance(start, str):
                        try:
                            start = datetime.fromisoformat(start)
                        except ValueError:
                            try:
                                start = date.fromisoformat(start)
                            except ValueError:
                                continue
                    if isinstance(end_dt, str):
                        try:
                            end_dt = datetime.fromisoformat(end_dt)
                        except ValueError:
                            try:
                                end_dt = date.fromisoformat(end_dt)
                            except ValueError:
                                end_dt = None
                    if isinstance(start, datetime) and start.tzinfo is not None:
                        start = start.replace(tzinfo=None)
                    if isinstance(end_dt, datetime) and end_dt is not None and end_dt.tzinfo is not None:
                        end_dt = end_dt.replace(tzinfo=None)
                    all_day = isinstance(start, date) and not isinstance(start, datetime)
                    events.append({
                        "summary": ev.get("summary", ""),
                        "start": start,
                        "end": end_dt,
                        "all_day": all_day,
                    })
                events.sort(key=lambda e: (
                    e["start"] if isinstance(e["start"], datetime)
                    else datetime.combine(e["start"], datetime.min.time())
                ))
                _LOGGER.info("Fetched %d calendar events", len(events))
            except Exception as exc:
                _LOGGER.warning("Could not fetch calendar events: %s", exc)

        # ── Fetch weather forecast ───────────────────────────────────────────
        forecast = []
        if show_weather and weather_entity:
            try:
                result = await hass.services.async_call(
                    "weather", "get_forecasts",
                    {"entity_id": weather_entity, "type": "daily"},
                    blocking=True,
                    return_response=True,
                )
                raw_fc = (result or {}).get(weather_entity, {}).get("forecast", [])
                for fc in raw_fc[:upcoming_days]:
                    forecast.append({
                        "datetime": fc.get("datetime", ""),
                        "condition": fc.get("condition", ""),
                        "temperature": fc.get("temperature"),
                        "templow": fc.get("templow"),
                        "precipitation_probability": fc.get("precipitation_probability"),
                    })
                _LOGGER.info("Fetched %d forecast entries", len(forecast))
            except Exception as exc:
                _LOGGER.warning("Could not fetch weather forecast: %s", exc)

        # ── Compose overlay ───────────────────────────────────────────────────
        try:
            jpeg_bytes = await hass.async_add_executor_job(
                compose_overlay, image_path, lang, events, opacity, font_size, show_date, show_calendar, show_weather, forecast, matte_type, matte_color
            )
        except Exception as exc:
            _LOGGER.error("Failed to compose overlay: %s", exc)
            return

        # ── Update image entity ───────────────────────────────────────────────
        image_entity = hass.data[DOMAIN].get(f"{entry.entry_id}_image_entity")
        if image_entity:
            await hass.async_add_executor_job(image_entity.update_image, jpeg_bytes)

        # ── Debug save ────────────────────────────────────────────────────────
        if debug_save:
            ts = datetime.now().strftime("%d%m%Y%H%M%S")
            debug_path = os.path.join(media_folder, f"frame_{ts}.jpg")
            try:
                with open(debug_path, "wb") as f:
                    f.write(jpeg_bytes)
                _LOGGER.info("Debug image saved: %s", debug_path)
            except Exception as exc:
                _LOGGER.warning("Could not save debug image: %s", exc)

        # ── Push to TV ────────────────────────────────────────────────────────
        try:
            await hass.async_add_executor_job(
                _push_to_tv, tv_ip, token_file, jpeg_bytes, matte
            )
        except Exception as exc:
            _LOGGER.error("Failed to push image to TV: %s", exc)
            return

        _LOGGER.info("Successfully pushed art to Samsung Frame at %s", tv_ip)

        # Set art mode brightness
        try:
            await hass.async_add_executor_job(_set_brightness, tv_ip, token_file, brightness)
        except Exception as exc:
            _LOGGER.warning("Could not set brightness: %s", exc)

    hass.services.async_register(
        DOMAIN, SERVICE_UPDATE, handle_update, schema=SERVICE_UPDATE_SCHEMA,
    )

    async def handle_delete_all_images(call: ServiceCall) -> None:
        """Query TV for all uploaded images and delete them one by one."""
        config = {**entry.data, **entry.options}
        tv_ip      = config[CONF_TV_IP]
        token_file = config.get(CONF_TOKEN_FILE, "/config/samsung_frame_token.txt")
        try:
            deleted = await hass.async_add_executor_job(_delete_all_tv_images, tv_ip, token_file)
            _LOGGER.info("Deleted %d images from Samsung Frame", deleted)
        except Exception as exc:
            _LOGGER.error("Failed to delete TV images: %s", exc)
            raise

    hass.services.async_register(
        DOMAIN, "delete_all_tv_images", handle_delete_all_images, schema=vol.Schema({})
    )

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


def _art_connect(tv_ip, token_file):
    """Open and handshake the art WebSocket channel. Returns open conn."""
    import websocket as ws_lib
    name_b64 = base64.b64encode(b"SamsungTvRemote").decode("utf-8")
    sslopt = {"cert_reqs": ssl.CERT_NONE}
    token = ""
    if token_file and os.path.exists(token_file):
        try:
            with open(token_file) as f:
                token = f.readline().strip()
        except Exception:
            pass
    art_url = f"wss://{tv_ip}:8002/api/v2/channels/com.samsung.art-app?name={name_b64}"
    if token:
        art_url += f"&token={token}"
    conn = ws_lib.create_connection(art_url, timeout=10, sslopt=sslopt)
    conn.settimeout(8)
    for _ in range(10):
        raw = conn.recv()
        resp = json.loads(raw)
        event = resp.get("event", "")
        if event == "ms.channel.connect":
            new_token = resp.get("data", {}).get("token")
            if new_token and token_file:
                with open(token_file, "w") as f:
                    f.write(new_token)
        elif event == "ms.channel.ready":
            break
    return conn


def _send_art_request(conn, data: dict):
    """Send an art_app_request over an open connection."""
    conn.send(json.dumps({
        "method": "ms.channel.emit",
        "params": {
            "event": "art_app_request",
            "to": "host",
            "data": json.dumps(data),
        },
    }))


def _delete_all_tv_images(tv_ip: str, token_file: str) -> int:
    """Delete only uploaded MY_ images and verify their removal from the TV."""
    from .art_protocol import delete_user_images

    conn = _art_connect(tv_ip, token_file)
    try:
        return delete_user_images(conn, _send_art_request)
    finally:
        conn.close()


def _set_brightness(tv_ip: str, token_file: str, brightness: int) -> None:
    """Set art mode brightness (1-10 scale as per Samsung API)."""
    import time
    conn = _art_connect(tv_ip, token_file)
    try:
        # Samsung API uses 1-10 scale, send in "value" field
        _send_art_request(conn, {
            "request": "set_brightness",
            "value": str(brightness),
        })
        time.sleep(0.5)
        _LOGGER.debug("Set art mode brightness to %d", brightness)
    finally:
        conn.close()


def _recv_until(conn, sub_events, max_msgs=15):
    for _ in range(max_msgs):
        try:
            raw = conn.recv()
        except Exception:
            break
        resp = json.loads(raw)
        if resp.get("event") == "d2d_service_message":
            data_str = resp.get("data", "{}")
            data = json.loads(data_str) if isinstance(data_str, str) else data_str
            if data.get("event") in sub_events:
                return data
    return None


def _push_to_tv(tv_ip, token_file, jpeg_bytes, matte):
    """Upload/select artwork with the transport required by the TV's Art API."""
    import time
    from .art_protocol import build_d2d_header, build_select_request, upload_mode_for_api

    conn = _art_connect(tv_ip, token_file)
    try:
        conn.settimeout(30)
        version = None
        for request_name in ("api_version", "get_api_version"):
            request_id = str(uuid.uuid4())
            _send_art_request(conn, {
                "request": request_name,
                "id": request_id,
                "request_id": request_id,
            })
            version_reply = _recv_until(conn, ["api_version", "error"], max_msgs=10)
            if version_reply and version_reply.get("version"):
                version = str(version_reply["version"])
                break

        mode = upload_mode_for_api(version)
        _LOGGER.info("Samsung Frame Art API version=%s upload_mode=%s", version, mode)

        if mode == "websocket_binary":
            upload_id = str(uuid.uuid4())
            inner = {
                "request": "send_image",
                "file_type": "JPEG",
                "matte_id": matte or "none",
                "id": upload_id,
            }
            outer = {
                "method": "ms.channel.emit",
                "params": {
                    "data": json.dumps(inner),
                    "to": "host",
                    "event": "art_app_request",
                },
            }
            header = json.dumps(outer, separators=(",", ":")).encode("utf-8")
            conn.send_binary(len(header).to_bytes(2, "big") + header + jpeg_bytes)
            data = _recv_until(conn, ["image_added", "error"], max_msgs=20)
        else:
            upload_id = str(uuid.uuid4())
            art_id = str(uuid.uuid4())
            file_type = "jpg"
            _send_art_request(conn, {
                "request": "send_image",
                "request_id": upload_id,
                "id": art_id,
                "conn_info": {
                    "d2d_mode": "socket",
                    "connection_id": random.randrange(4 * 1024 * 1024 * 1024),
                    "id": art_id,
                },
                "image_date": datetime.now().strftime("%Y:%m:%d %H:%M:%S"),
                "matte_id": matte or "none",
                "portrait_matte_id": matte or "none",
                "file_type": file_type,
                "file_size": len(jpeg_bytes),
            })
            ready = _recv_until(conn, ["ready_to_use", "error"], max_msgs=20)
            if not ready or ready.get("event") == "error":
                raise RuntimeError(f"TV did not authorize D2D image transfer: {ready}")

            conn_info = ready.get("conn_info")
            if isinstance(conn_info, str):
                conn_info = json.loads(conn_info)
            if not isinstance(conn_info, dict) or not conn_info.get("ip") or not conn_info.get("port"):
                raise RuntimeError(f"TV returned invalid D2D connection info: {ready}")

            transfer_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            transfer_socket.settimeout(30)
            if conn_info.get("secured"):
                time.sleep(0.1)
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                transfer_socket = context.wrap_socket(transfer_socket)
            try:
                transfer_socket.connect((conn_info["ip"], int(conn_info["port"])))
                transfer_socket.sendall(build_d2d_header(
                    len(jpeg_bytes), file_type, conn_info.get("key", "")
                ))
                transfer_socket.sendall(jpeg_bytes)
            finally:
                transfer_socket.close()
            data = _recv_until(conn, ["image_added", "error"], max_msgs=20)

        if data is None:
            raise RuntimeError("TV did not confirm the uploaded image (no image_added event)")
        if data.get("event") == "error":
            raise RuntimeError(f"TV rejected image upload: {data}")

        content_id = data.get("content_id")
        if not content_id:
            raise RuntimeError(f"TV confirmed upload without a content_id: {data}")
        _LOGGER.info("Image added, content_id=%s", content_id)

        select_request_id = str(uuid.uuid4())
        _send_art_request(conn, build_select_request(content_id, select_request_id))
        _LOGGER.info("Requested display of uploaded artwork, content_id=%s", content_id)
        time.sleep(1)
    finally:
        conn.close()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.services.async_remove(DOMAIN, SERVICE_UPDATE)
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
