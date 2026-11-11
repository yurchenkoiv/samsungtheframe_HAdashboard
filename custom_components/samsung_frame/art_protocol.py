"""Helpers for selecting Samsung Frame Art API upload transports."""
from __future__ import annotations

import json


def upload_mode_for_api(version: str | None) -> str:
    """Return the upload transport used by a Samsung Frame Art API version.

    2017/2018 API versions (<2) use the SmartThings-style WebSocket binary
    frame. API 2.x and newer use the D2D TCP socket handshake.
    """
    try:
        major = int(str(version).split(".", 1)[0])
    except (TypeError, ValueError):
        # Preserve the integration's previous upload behavior when the TV
        # does not answer the version query.
        return "websocket_binary"
    return "websocket_binary" if major < 2 else "d2d_socket"


def build_select_request(content_id: str, request_id: str) -> dict[str, object]:
    """Build a correlated select_image request for current Frame Art APIs."""
    return {
        "request": "select_image",
        "category_id": None,
        "content_id": content_id,
        "show": True,
        "id": request_id,
        "request_id": request_id,
    }


def build_d2d_header(file_size: int, file_type: str, sec_key: str) -> bytes:
    """Build the length-prefixed D2D upload header used by API 2.x+."""
    header = json.dumps(
        {
            "num": 0,
            "total": 1,
            "fileLength": file_size,
            "fileName": "dummy",
            "fileType": file_type,
            "secKey": sec_key,
            "version": "0.0.1",
        }
    ).encode("ascii")
    return len(header).to_bytes(4, "big") + header
