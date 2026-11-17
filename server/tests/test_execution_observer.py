"""Exercise directed ComfyUI delivery separately from opt-in monitoring."""
import asyncio
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nodeui_bridge.execution_observer import FLAG, install


class Server:
    def __init__(self):
        self.sockets_metadata = {
            "owner": {"feature_flags": {FLAG: True}},
            "observer": {"feature_flags": {FLAG: True}},
            "browser": {"feature_flags": {}},
        }
        self.last_prompt_id, self.last_node_id = "external-1", "7"
        self.queue, self.delivered = [], []

    def send_sync(self, event, data, sid=None):
        self.queue.append((event, data, sid))

    async def send(self, event, data, sid=None):
        self.delivered.append((event, data, sid))

    async def send_bytes(self, event, data, sid=None):
        self.delivered.append((event, data, sid))

    async def flush(self):
        while self.queue:
            await self.send(*self.queue.pop(0))


class ExecutionObserverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.server = Server()
        self.assertTrue(install(self.server))

    async def test_only_opted_in_other_clients_receive_execution(self):
        data = {"prompt_id": "external-1", "node": "7", "value": 17, "max": 25}
        self.server.send_sync("progress", data, "owner")
        await self.server.flush()
        self.assertEqual(self.server.delivered, [
            ("progress", data, "owner"),
            ("nodeui_execution", {"type": "progress", "data": data}, "observer"),
        ])

    async def test_legacy_preview_identity_is_captured_before_next_job(self):
        image = ("PNG", object(), 512)
        self.server.send_sync(2, image, "owner")
        self.server.last_prompt_id, self.server.last_node_id = "next-job", "99"
        await self.server.flush()
        self.assertEqual(self.server.delivered, [
            (2, image, "owner"),
            (4, (image, {"prompt_id": "external-1", "node_id": "7"}), "observer"),
        ])

    async def test_metadata_preview_keeps_job_and_does_not_mutate_owner_metadata(self):
        metadata = {"prompt_id": "metadata-job", "node_id": "7:2"}
        image = ("PNG", object(), 512)
        self.server.send_sync(4, (image, metadata), "owner")
        metadata["node_id"] = "changed-after-enqueue"
        await self.server.flush()
        self.assertEqual(self.server.delivered[1],
                         (4, (image, {"prompt_id": "metadata-job", "node_id": "7:2"}), "observer"))

    async def test_encoded_legacy_frame_becomes_prompt_scoped(self):
        import json
        image = b"test-image-bytes"
        self.server.send_sync(1, struct.pack(">I", 2) + image, "owner")
        await self.server.flush()
        event, data, sid = self.server.delivered[1]
        self.assertEqual((event, sid), (4, "observer"))
        length = struct.unpack(">I", data[:4])[0]
        self.assertEqual(json.loads(data[4:4 + length])["prompt_id"], "external-1")
        self.assertEqual(data[4 + length:], image)

    async def test_broadcasts_are_not_duplicated_and_unrelated_events_are_not_relayed(self):
        self.server.send_sync("progress", {"prompt_id": "external-1"})
        self.server.send_sync("private-extension-event", {"secret": "value"}, "owner")
        await self.server.flush()
        self.assertEqual(len(self.server.delivered), 2)

    async def test_disconnect_and_reinstall_do_not_duplicate_or_break_owner_delivery(self):
        self.assertTrue(install(self.server))
        self.server.send_sync("execution_success", {"prompt_id": "external-1"}, "owner")
        del self.server.sockets_metadata["observer"]
        await self.server.flush()
        self.assertEqual(self.server.delivered, [("execution_success", {"prompt_id": "external-1"}, "owner")])

    async def test_unidentified_preview_is_not_relayed(self):
        self.server.last_prompt_id = None
        self.server.send_sync(2, ("PNG", object(), 512), "owner")
        await self.server.flush()
        self.assertEqual(len(self.server.delivered), 1)

    def test_older_server_without_transport_support_is_left_unchanged(self):
        self.assertFalse(install(object()))
