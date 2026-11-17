"""Opt-in observation without replacing the submitting client's WebSocket session."""
from __future__ import annotations

from functools import wraps
import json
import logging
import struct


FLAG = "nodeui_observe_execution"
RELAY = "_nodeui_execution_relay"
EVENTS = {"execution_start", "executing", "progress", "progress_state", "execution_cached",
          "executed", "execution_success", "execution_error", "execution_interrupted"}


def install(server) -> bool:
    if getattr(server, "_nodeui_execution_observer", False):
        return True
    if not all(hasattr(server, name) for name in ("send", "send_sync", "sockets_metadata", "send_bytes")):
        return False
    original_send, original_sync = server.send, server.send_sync

    def observers(owner):
        return [sid for sid, metadata in list(server.sockets_metadata.items())
                if sid != owner and metadata.get("feature_flags", {}).get(FLAG) is True]

    @wraps(original_sync)
    def send_sync(event, data, sid=None):
        result = original_sync(event, data, sid)
        # Broadcasts already reach observers. Never send them twice.
        if sid is None or not observers(sid):
            return result
        prompt = getattr(server, "last_prompt_id", None)
        node = getattr(server, "last_node_id", None)
        if event in EVENTS and isinstance(data, dict):
            payload = ("message", event, {"prompt_id": prompt, **data})
        elif event == 2:  # UNENCODED_PREVIEW_IMAGE
            payload = ("image", 4, (data, {"prompt_id": prompt, "node_id": node}))
        elif event == 4 and isinstance(data, tuple) and len(data) == 2 and isinstance(data[1], dict):
            payload = ("image", 4, (data[0], dict(data[1])))
        elif event == 1 and isinstance(data, (bytes, bytearray)) and len(data) > 4:
            if not prompt:
                return result
            image_type = struct.unpack(">I", data[:4])[0]
            if image_type not in (1, 2):
                return result
            metadata = json.dumps({"prompt_id": prompt, "node_id": node,
                                   "image_type": "image/png" if image_type == 2 else "image/jpeg"}).encode()
            payload = ("bytes", 4, struct.pack(">I", len(metadata)) + metadata + bytes(data[4:]))
        else:
            return result
        # Freeze legacy packet identity on the execution thread, before another job starts.
        original_sync(RELAY, payload, sid)
        return result

    @wraps(original_send)
    async def send(event, data, sid=None):
        if event != RELAY:
            return await original_send(event, data, sid)
        kind, source_event, payload = data
        for observer in observers(sid):
            try:
                if kind == "message":
                    await original_send("nodeui_execution", {"type": source_event, "data": payload}, observer)
                elif kind == "bytes":
                    await server.send_bytes(source_event, payload, observer)
                else:
                    metadata = payload[1]
                    if not metadata.get("prompt_id"):
                        continue  # An unidentified frame must not replace another job's preview.
                    await original_send(source_event, (payload[0], dict(metadata)), observer)
            except Exception:
                # An observer must never stop delivery to the job's submitting client.
                logging.exception("NodeUI execution observer delivery failed")

    server.send_sync, server.send = send_sync, send
    server._nodeui_execution_observer = True
    return True
