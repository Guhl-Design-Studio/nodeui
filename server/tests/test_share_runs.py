import asyncio
import sys
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from aiohttp import web
    from nodeui_bridge.share_runs import ShareRuns
    from nodeui_bridge.filesystem import Root
except ModuleNotFoundError as error:
    if error.name != "aiohttp":
        raise
    ShareRuns = None


@unittest.skipUnless(ShareRuns, "Requires aiohttp")
class SharedRunTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name)
        self.root = Root("output", "Outputs", "output", self.path)
        self.runs = ShareRuns(self.path / "runs.sqlite3")
        self.calls = 0
        self.history = {}
        self.queue = SimpleNamespace(get_history=lambda prompt_id: self.history,
                                     get_current_queue=lambda: ([], [(0, "one"), (1, "two")]))

    async def submit(self, token, job):
        async def body():
            return {"nodeui_receipt": token, "nodeui_output": "2",
                    "prompt": {"2": {"class_type": "NodeUIReturnImage"}}}

        async def submit(request):
            self.calls += 1
            await asyncio.sleep(0)
            return web.json_response({"prompt_id": job})
        return await self.runs.submit("owner", SimpleNamespace(json=body), submit)

    async def test_out_of_order_batch_cached_output_and_owner(self):
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        await asyncio.gather(self.submit(a, "one"), self.submit(b, "two"))
        for job, token in [("two", b), ("one", a)]:
            images = [{"type": "output", "filename": name} for name in [job + ".png", "extra.png"]]
            (self.path / images[0]["filename"]).write_bytes(job.encode())
            self.history[job] = {"status": {"status_str": "success"},
                                 "outputs": {"2": {"images": images}, "9": {"images": images[::-1]}}}
            result = await self.runs.result("owner", token, self.queue, self.root)
            self.assertEqual(result._path.read_bytes(), job.encode())
            del self.history[job]
            # Reopening the database after history eviction still serves the same first image.
            again = await ShareRuns(self.runs.database).result("owner", token, self.queue, self.root)
            self.assertEqual(again._path, result._path)
            with self.assertRaises(web.HTTPNotFound):
                await self.runs.result("different user", token, self.queue, self.root)

    async def test_failed_or_missing_run_never_returns_another_image(self):
        token = str(uuid.uuid4())
        await self.submit(token, "one")
        self.history["one"] = {"status": {"status_str": "error"}, "outputs": {}}
        with self.assertRaises(web.HTTPUnprocessableEntity):
            await self.runs.result("owner", token, self.queue, self.root)
        token = str(uuid.uuid4())
        await self.submit(token, "gone")
        with self.assertRaises(web.HTTPGone):
            await self.runs.result("owner", token, self.queue, self.root)

    async def test_one_submission_per_receipt_even_if_response_is_lost(self):
        token = str(uuid.uuid4())
        first, second = await asyncio.gather(self.submit(token, "one"), self.submit(token, "two"),
                                             return_exceptions=True)
        self.assertEqual(json.loads(first.body)["prompt_id"], "one")
        self.assertIsInstance(second, web.HTTPConflict)
        result = await self.submit(token, "two")
        self.assertEqual(json.loads(result.body)["prompt_id"], "one")
        self.assertEqual(self.calls, 1)
        pending = await self.runs.result("owner", token, self.queue, self.root, wait_seconds=0)
        self.assertEqual(pending.status, 202)
