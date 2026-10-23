"""Downloads use local fixtures; no provider account or model download required."""
import asyncio
import errno
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from aiohttp import web
    from aiohttp.test_utils import TestServer
    from comfymobile_bridge.downloads import DownloadManager, checked_url, discover, fetch, filename
    from comfymobile_bridge.filesystem import Root
    READY = True
except ImportError:
    READY = False


@unittest.skipUnless(READY, "Requires aiohttp")
class DownloadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Root("model:loras", "Loras", "models", Path(self.temp.name), True)
        self.manager = DownloadManager()
        self.slow_started = asyncio.Event()
        app = web.Application()

        async def file(request):
            return web.Response(body=b"model-data", headers={"Content-Disposition": 'attachment; filename="actual.safetensors"'})

        async def large(request):
            response = web.StreamResponse()
            await response.prepare(request)
            for _ in range(101):
                await response.write(b"x" * (1024 * 1024))
            await response.write_eof()
            return response

        async def slow(request):
            response = web.StreamResponse()
            await response.prepare(request)
            await response.write(b"partial")
            self.slow_started.set()
            await asyncio.sleep(0.2)
            return response

        app.router.add_get("/file", file)
        app.router.add_get("/large", large)
        app.router.add_get("/slow", slow)
        async def html(request):
            return web.Response(text="<html>login</html>", content_type="text/html")

        async def denied(request):
            return web.Response(status=403)

        app.router.add_get("/html", html)
        app.router.add_get("/denied", denied)
        self.server = TestServer(app)
        await self.server.start_server()

    async def asyncTearDown(self):
        await self.manager.close()
        await self.server.close()
        self.temp.cleanup()

    async def finish(self, job):
        task = self.manager.tasks.get(job["id"])
        if task:
            await asyncio.gather(task, return_exceptions=True)
        return self.manager.jobs[job["id"]]

    def create(self, endpoint="/file", name=None, path="nested"):
        return self.manager.create("alice", self.root, path, str(self.server.make_url(endpoint)), None, name)

    async def test_streams_and_uses_response_filename_without_overwriting(self):
        first, second = await asyncio.gather(self.finish(self.create()), self.finish(self.create()))
        self.assertEqual(first["state"], "completed")
        self.assertEqual(second["state"], "completed")
        files = list((self.root.path / "nested").iterdir())
        self.assertEqual({p.name for p in files}, {"actual.safetensors", "actual_1.safetensors"})
        self.assertTrue(all(p.read_bytes() == b"model-data" for p in files))
        self.assertEqual(self.manager.list("bob"), [])
        with self.assertRaises(FileNotFoundError):
            self.manager.cancel(first["id"], "bob")

    async def test_downloads_without_hard_links_keep_duplicate_files_and_clean_staging(self):
        with patch("comfymobile_bridge.filesystem.os.link", side_effect=OSError(errno.EOPNOTSUPP, "No hard links")):
            first, second = await asyncio.gather(self.finish(self.create()), self.finish(self.create()))
        self.assertEqual([first["state"], second["state"]], ["completed", "completed"])
        files = list((self.root.path / "nested").iterdir())
        self.assertEqual({p.name for p in files}, {"actual.safetensors", "actual_1.safetensors"})
        self.assertTrue(all(p.read_bytes() == b"model-data" for p in files))

    async def test_unsupported_destination_is_rejected_before_streaming(self):
        with patch("comfymobile_bridge.filesystem.os.link", side_effect=OSError(errno.EOPNOTSUPP, "No hard links")):
            with patch("comfymobile_bridge.filesystem._rename_exclusive", side_effect=OSError(errno.ENOTSUP, "No exclusive rename")):
                job = await self.finish(self.create("/large", "large.bin"))
        self.assertEqual(job["state"], "failed")
        self.assertEqual(job["receivedBytes"], 0)
        self.assertIn("Choose another location", job["error"])
        self.assertEqual(list((self.root.path / "nested").iterdir()), [])

    async def test_download_exceeds_upload_limit_and_unknown_size(self):
        job = await self.finish(self.create("/large", "large.bin"))
        self.assertEqual(job["state"], "completed")
        self.assertEqual(job["receivedBytes"], 101 * 1024 * 1024)
        self.assertIsNone(job["totalBytes"])
        self.assertEqual((self.root.path / job["path"]).stat().st_size, job["receivedBytes"])

    async def test_cancel_cleans_partial_and_queue(self):
        active = self.create("/slow", "cancel.bin")
        await self.slow_started.wait()
        self.manager.cancel(active["id"], "alice")
        job = await self.finish(active)
        self.assertEqual(job["state"], "cancelled")
        self.assertEqual(list(self.root.path.rglob("*.*")), [])
        jobs = [self.create("/slow", f"queue{i}.bin") for i in range(4)]
        self.manager.cancel(jobs[-1]["id"], "alice")
        await asyncio.gather(*(self.finish(job) for job in jobs))
        self.assertEqual(self.manager.jobs[jobs[-1]["id"]]["state"], "cancelled")

    async def test_html_and_access_errors_do_not_publish_files(self):
        for endpoint in ["/html", "/denied"]:
            job = await self.finish(self.create(endpoint))
            self.assertEqual(job["state"], "failed")
            self.assertIsNotNone(job["error"])
        self.assertFalse((self.root.path / "nested").exists())

    async def test_disk_failure_cleans_partial(self):
        with patch("comfymobile_bridge.filesystem.os.link", side_effect=OSError("disk full")):
            job = await self.finish(self.create())
        self.assertEqual(job["state"], "failed")
        self.assertEqual(list((self.root.path / "nested").iterdir()), [])

    async def test_paths_and_outward_symlinks_are_rejected(self):
        for name in ["../escape", "C:\\evil", "a/b", ".secret", ""]:
            with self.assertRaises(ValueError):
                filename(name)
        for url in ["file:///tmp/file", "https://user:secret@example.com/f", "not a url"]:
            with self.assertRaises(ValueError):
                checked_url(url)
        with tempfile.TemporaryDirectory() as outside:
            (self.root.path / "outside").symlink_to(outside)
            with self.assertRaises(ValueError):
                self.create(path="outside")

    async def test_provider_token_stripped_on_redirect_and_downgrade_rejected(self):
        redirect = Mock(status=302, headers={"Location": "https://cdn.example.com/model"})
        success = Mock(status=200)
        session = Mock(get=AsyncMock(side_effect=[redirect, success]))
        await fetch(session, "https://huggingface.co/org/repo/resolve/main/a", "secret")
        self.assertEqual(session.get.call_args_list[0].kwargs["headers"], {"Authorization": "Bearer secret"})
        self.assertEqual(session.get.call_args_list[1].kwargs["headers"], {})
        session.get = AsyncMock(return_value=Mock(status=302, headers={"Location": "http://cdn.example.com/a"}))
        with self.assertRaises(ValueError):
            await fetch(session, "https://civitai.com/api/download/models/1", "secret")

    async def test_huggingface_blob_and_repository_pagination(self):
        result = await discover("https://huggingface.co/org/repo/blob/main/folder/a.safetensors")
        self.assertEqual(result["files"][0]["url"], "https://huggingface.co/org/repo/resolve/main/folder/a.safetensors")
        response = Mock(json=AsyncMock(return_value=[{"path": "folder/a.bin", "type": "file", "size": 12}]), links={"next": {"url": "https://huggingface.co/api/models/org/repo/tree/main?cursor=next"}})
        with patch("comfymobile_bridge.downloads.fetch", AsyncMock(return_value=response)) as mocked:
            result = await discover("https://huggingface.co/org/repo/tree/main/folder", "key", cursor="page")
            self.assertIn("/tree/main/folder?limit=100&cursor=page", mocked.call_args.args[1])
            self.assertEqual(result["nextCursor"], "next")
            await discover("https://huggingface.co/org/repo/tree/main/folder", folder="")
            self.assertIn("/tree/main?", mocked.call_args.args[1])

    async def test_civitai_version_and_file_metadata(self):
        version = {"name": "v2", "files": [{"name": "a.safetensors", "sizeKB": 2, "downloadUrl": "https://civitai.com/api/download/models/123", "metadata": {"format": "SafeTensor"}}]}
        with patch("comfymobile_bridge.downloads.metadata", AsyncMock(return_value=version)) as mocked:
            result = await discover("https://civitai.com/models/9/test?modelVersionId=123", "key")
            self.assertTrue(mocked.call_args.args[1].endswith("model-versions/123"))
            self.assertEqual(result["files"][0]["version"], "v2")
            self.assertEqual(result["files"][0]["size"], 2048)
        with patch("comfymobile_bridge.downloads.metadata", AsyncMock(return_value={"modelVersions": [version, version]})):
            result = await discover("https://civitai.com/models/9")
            self.assertEqual(len(result["files"]), 2)
