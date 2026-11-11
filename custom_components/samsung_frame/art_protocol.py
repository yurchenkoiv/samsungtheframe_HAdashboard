"""Helpers for Samsung Frame Art API transports and confirmed requests."""
from __future__ import annotations

import json
import time
import uuid


def upload_mode_for_api(version: str | None) -> str:
    """Return the upload transport used by a Samsung Frame Art API version."""
    try:
        major = int(str(version).split(".", 1)[0])
    except (TypeError, ValueError):
        return "websocket_binary"
    return "websocket_binary" if major < 2 else "d2d_socket"


def build_select_request(content_id: str, request_id: str) -> dict[str, object]:
    """Build a correlated select_image request for current Frame Art APIs."""
    return {
        "request": "select_image", "category_id": None,
        "content_id": content_id, "show": True,
        "id": request_id, "request_id": request_id,
    }


def build_d2d_header(file_size: int, file_type: str, sec_key: str) -> bytes:
    """Build the length-prefixed D2D upload header used by API 2.x+."""
    header = json.dumps({
        "num": 0, "total": 1, "fileLength": file_size,
        "fileName": "dummy", "fileType": file_type, "secKey": sec_key,
        "version": "0.0.1",
    }).encode("ascii")
    return len(header).to_bytes(4, "big") + header


def _confirmed_request(conn, send, request, events):
    """Wait only for this request; bound both elapsed time and message count."""
    request_id = str(uuid.uuid4())
    request = {**request, "id": request_id, "request_id": request_id}
    send(conn, request)
    deadline = time.monotonic() + 10
    for _ in range(100):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        conn.settimeout(remaining)
        try:
            response = json.loads(conn.recv())
        except (TimeoutError, OSError) as exc:
            raise RuntimeError(f"No confirmation for {request['request']}") from exc
        if not isinstance(response, dict) or response.get("event") != "d2d_service_message":
            continue
        data = response.get("data", {})
        if isinstance(data, str):
            data = json.loads(data)
        if not isinstance(data, dict):
            continue
        if data.get("request_id", data.get("id")) != request_id:
            continue
        if data.get("event") == "error":
            raise RuntimeError(f"TV rejected {request['request']}: {data.get('error_code', 'unknown error')}")
        if events is None or data.get("event") in events:
            return data
    raise RuntimeError(f"No confirmation for {request['request']}")


def _content_list(conn, send):
    """Read the catalog; MY is not a portable category ID across firmware."""
    data = _confirmed_request(conn, send,
                              {"request": "get_content_list", "category": None},
                              {"content_list", "get_content_list"})
    items = data.get("content_list")
    if isinstance(items, str):
        items = json.loads(items)
    if not isinstance(items, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("content_id"), str)
        or not item["content_id"] for item in items
    ):
        raise RuntimeError("TV returned an invalid content list; deletion not confirmed")
    return items


def delete_user_images(conn, send):
    """Delete only original MY_ uploads, requiring replies and read-back proof."""
    items = _content_list(conn, send)
    # Catalogs can include purchased/preinstalled art even in a MY category.
    # Fail closed for unknown ID formats; never infer ownership from category alone.
    original = {item["content_id"] for item in items
                if item["content_id"].startswith("MY_")
                and item.get("content_type") not in ("server", "preinstall")}
    if not original:
        return 0
    for content_id in sorted(original):
        expected = [{"content_id": content_id}]
        reply = _confirmed_request(conn, send,
                                   {"request": "delete_image_list", "content_id_list": expected},
                                   None)  # Reply names vary; validate correlated IDs below.
        acknowledged = reply.get("content_id_list")
        if isinstance(acknowledged, str):
            acknowledged = json.loads(acknowledged)
        if acknowledged != expected:
            raise RuntimeError("TV did not confirm the requested deletion")
    remaining = original
    for attempt in range(3):
        remaining = original.intersection(item["content_id"] for item in _content_list(conn, send))
        if not remaining:
            return len(original)
        if attempt < 2:
            time.sleep(0.3)
    raise RuntimeError(f"Deletion not confirmed: {len(remaining)} original uploaded images remain")
