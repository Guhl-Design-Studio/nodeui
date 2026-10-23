"""Exercise the real aiohttp handlers with minimal ComfyUI folder/user fixtures."""
import importlib
import errno
import io
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

try:
    from aiohttp import FormData, web
    from aiohttp.test_utils import TestClient, TestServer
    from PIL import Image
    HTTP_DEPENDENCIES = True
except ImportError:
    HTTP_DEPENDENCIES = False

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@unittest.skipUnless(HTTP_DEPENDENCIES, "HTTP tests require aiohttp and Pillow (included with ComfyUI)")
class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        for name in ["input", "output", "temp", "workflows", "models"]:
            (self.base / name).mkdir()
        folder_paths = types.ModuleType("folder_paths")
        folder_paths.get_input_directory = lambda: str(self.base / "input")
        folder_paths.get_output_directory = lambda: str(self.base / "output")
        folder_paths.get_temp_directory = lambda: str(self.base / "temp")
        folder_paths.folder_names_and_paths = {"loras": ([str(self.base / "models")], {".safetensors"})}
        server = types.ModuleType("server")
        instance = types.SimpleNamespace(
            routes=web.RouteTableDef(),
            user_manager=types.SimpleNamespace(get_request_user_filepath=lambda request, file, create_dir=False: str(self.base / "workflows")),
        )
        server.PromptServer = types.SimpleNamespace(instance=instance)
        sys.modules["folder_paths"] = folder_paths
        sys.modules["server"] = server
        # Rebuild route decorators for this isolated app instead of sharing route tables.
        sys.modules.pop("comfymobile_bridge.routes", None)
        self.routes = importlib.import_module("comfymobile_bridge.routes")
        app = web.Application()
        app.add_routes(instance.routes)
        self.routes.configure_downloads(app)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.temporary.cleanup()

    async def test_capabilities_exposes_only_logical_roots(self):
        response = await self.client.get("/comfymobile/v1/capabilities")
        value = await response.json()
        self.assertEqual(value["apiVersion"], 1)
        self.assertEqual(value["roots"][0]["id"], "workflows")
        self.assertNotIn("path", value["roots"][0])
        self.assertTrue(value["downloads"])
        self.assertTrue(value["fileUploads"])
        self.assertTrue(value["fileDeletion"])
        self.assertTrue(value["resourceMonitoring"])
        self.assertEqual(value["version"], "1.4.1")
        self.assertTrue(all(root["deletable"] for root in value["roots"]))

    async def test_resource_endpoint_returns_optional_sensors_without_gpu_drivers(self):
        sample = {"sampledAt": 1792695000, "cpuPercent": None,
                  "ram": {"usedBytes": 1024, "totalBytes": 8192}, "gpu": None}
        with patch.object(self.routes.resource_collector, "sample", return_value=sample):
            response = await self.client.get("/comfymobile/v1/resources")
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.json(), sample)

    async def test_model_category_merges_locations_and_keeps_legacy_indexes(self):
        first = self.base / "models"
        second = self.base / "extra_models"
        second.mkdir()
        (first / "shared.bin").write_bytes(b"primary")
        (second / "shared.bin").write_bytes(b"secondary")
        (second / "extra.bin").write_bytes(b"extra")
        self.routes.folder_paths.folder_names_and_paths.update({
            "loras": ([str(first), str(self.base / "missing"), str(second), str(first / ".")], {".bin"}),
            "missing_models": ([str(self.base / "missing")], {".bin"}),
        })
        caps = await (await self.client.get("/comfymobile/v1/capabilities")).json()
        models = [v for v in caps["roots"] if v["kind"] == "models"]
        self.assertEqual([{k: v for k, v in root.items() if k != "downloadDestinations"} for root in models], [{"id": "model:loras", "name": "Loras", "kind": "models", "writable": False, "deletable": True}])
        self.assertEqual(len(models[0]["downloadDestinations"]), 2)
        listing = await (await self.client.get("/comfymobile/v1/files?root=model:loras")).json()
        self.assertEqual([v["name"] for v in listing["entries"]], ["extra.bin", "shared.bin"])
        response = await self.client.get("/comfymobile/v1/content?root=model:loras&path=shared.bin")
        self.assertEqual(await response.read(), b"primary")
        response = await self.client.get("/comfymobile/v1/content?root=model:loras:2&path=shared.bin")
        self.assertEqual(await response.read(), b"secondary")
        response = await self.client.get("/comfymobile/v1/content?root=model:loras&path=extra.bin")
        self.assertEqual(await response.read(), b"extra")

    async def test_listing_and_content_range(self):
        (self.base / "output" / "movie.mp4").write_bytes(b"0123456789")
        listing = await (await self.client.get("/comfymobile/v1/files?root=output")).json()
        self.assertEqual(listing["entries"][0]["mimeType"], "video/mp4")
        response = await self.client.get("/comfymobile/v1/content?root=output&path=movie.mp4", headers={"Range": "bytes=2-5"})
        self.assertEqual(response.status, 206)
        self.assertEqual(await response.read(), b"2345")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    async def test_delete_files_in_each_configured_root(self):
        for root, folder in [("input", "input"), ("output", "output"), ("temp", "temp"), ("workflows", "workflows"), ("model:loras", "models")]:
            with self.subTest(root=root):
                path = self.base / folder / "a + 日本.bin"
                path.write_bytes(b"remove")
                keep = self.base / folder / "keep.bin"
                keep.write_bytes(b"keep")
                response = await self.client.delete("/comfymobile/v1/files", params={"root": root, "path": path.name})
                self.assertEqual(response.status, 204)
                self.assertFalse(path.exists())
                self.assertEqual(keep.read_bytes(), b"keep")
                response = await self.client.delete("/comfymobile/v1/files", params={"root": root, "path": path.name})
                self.assertEqual(response.status, 404)

    async def test_delete_rejects_directories_escapes_and_missing_user(self):
        (self.base / "output" / "nested").mkdir()
        for query in [{"root": "unknown", "path": "a.bin"}, {"root": "output", "path": ""},
                      {"root": "output", "path": "nested"}, {"root": "output", "path": "../secret"}]:
            response = await self.client.delete("/comfymobile/v1/files", params=query)
            self.assertEqual(response.status, 403)
        file = self.base / "output" / "keep.bin"
        file.write_bytes(b"keep")
        self.routes.PromptServer.instance.user_manager.get_request_user_filepath = lambda *args, **kwargs: None
        response = await self.client.delete("/comfymobile/v1/files", params={"root": "output", "path": file.name})
        self.assertEqual(response.status, 403)
        self.assertTrue(file.exists())

    async def test_upload_and_copy(self):
        data = FormData()
        data.add_field("file", b"new image", filename="a.png", content_type="image/png")
        response = await self.client.post("/comfymobile/v1/upload?root=input&path=mobile", data=data)
        self.assertEqual(response.status, 201)
        self.assertEqual((await response.json())["path"], "mobile/a.png")
        (self.base / "output" / "result.png").write_bytes(b"result")
        response = await self.client.post("/comfymobile/v1/copy", json={"root": "output", "path": "result.png"})
        value = await response.json()
        self.assertEqual(response.status, 200)
        self.assertEqual(value["subfolder"], "")
        self.assertEqual(value["file"]["path"], "result.png")
        self.assertEqual((self.base / "input" / "result.png").read_bytes(), b"result")
        self.assertEqual(value["type"], "input")

    async def test_thumbnail_size_and_image_format(self):
        Image.new("RGB", (1024, 512), "blue").save(self.base / "output" / "large.png")
        response = await self.client.get("/comfymobile/v1/thumbnail?root=output&path=large.png&width=128")
        self.assertEqual(response.content_type, "image/jpeg")
        image = Image.open(io.BytesIO(await response.read()))
        self.assertEqual(image.size, (128, 64))

    async def test_unknown_roots_and_escapes_are_denied(self):
        for query in ["root=unknown", "root=input&path=../secret", "root=input&path=C:%5Csecret"]:
            response = await self.client.get("/comfymobile/v1/content?" + query)
            self.assertEqual(response.status, 403)

    async def test_readonly_model_upload_and_copy_are_denied(self):
        form = FormData()
        form.add_field("file", b"weights", filename="weights.bin")
        response = await self.client.post("/comfymobile/v1/upload?root=model:loras", data=form)
        self.assertEqual(response.status, 403)
        response = await self.client.post("/comfymobile/v1/copy", json={"root": "model:loras:0", "path": "weights.bin"})
        self.assertEqual(response.status, 403)


    async def test_device_upload_without_hard_links_preserves_duplicate_files(self):
        query = {"root": "output", "location": self.routes.location_id(self.base / "output"), "filename": "model.bin"}
        with patch("comfymobile_bridge.filesystem.os.link", side_effect=OSError(errno.EOPNOTSUPP, "No hard links")):
            for name in ["model.bin", "model_1.bin"]:
                response = await self.client.post("/comfymobile/v1/upload-file", params=query, data=b"complete")
                self.assertEqual(response.status, 201)
                self.assertEqual((await response.json())["name"], name)
        self.assertEqual({p.name for p in (self.base / "output").iterdir()}, {"model.bin", "model_1.bin"})
        self.assertTrue(all(p.read_bytes() == b"complete" for p in (self.base / "output").iterdir()))

    async def test_unsupported_upload_destination_does_not_publish_a_file(self):
        query = {"root": "output", "location": self.routes.location_id(self.base / "output"), "filename": "model.bin"}
        with patch("comfymobile_bridge.filesystem.os.link", side_effect=OSError(errno.EOPNOTSUPP, "No hard links")):
            with patch("comfymobile_bridge.filesystem._rename_exclusive", side_effect=OSError(errno.ENOTSUP, "No exclusive rename")):
                response = await self.client.post("/comfymobile/v1/upload-file", params=query, data=b"complete")
        self.assertEqual(response.status, 403)
        self.assertEqual(list((self.base / "output").iterdir()), [])

    async def test_device_upload_selects_location_and_preserves_existing_files(self):
        extra = self.base / "extra_models"
        (extra / "nested").mkdir(parents=True)
        self.routes.folder_paths.folder_names_and_paths["loras"] = ([str(self.base / "models"), str(extra)], {".bin"})
        locations = await (await self.client.get("/comfymobile/v1/downloads/locations?root=model:loras&path=nested")).json()
        query = {"root": "model:loras", "path": "nested", "location": locations["defaultLocation"], "filename": "a + model.bin"}
        for expected in ["a + model.bin", "a + model_1.bin"]:
            response = await self.client.post("/comfymobile/v1/upload-file", params=query, data=b"model bytes")
            self.assertEqual(response.status, 201)
            self.assertEqual((await response.json())["path"], "nested/" + expected)
            self.assertEqual((extra / "nested" / expected).read_bytes(), b"model bytes")
        self.assertFalse((self.base / "models/nested").exists())
        self.assertFalse(list(extra.rglob(".comfymobile-upload-*")))

    async def test_device_upload_streams_more_than_legacy_limit(self):
        async def chunks():
            for _ in range(101):
                yield b"x" * (1024 * 1024)
        query = {"root": "model:loras", "location": self.routes.location_id(self.base / "models"), "filename": "large.bin"}
        response = await self.client.post("/comfymobile/v1/upload-file", params=query, data=chunks())
        self.assertEqual(response.status, 201)
        self.assertEqual((await response.json())["size"], 101 * 1024 * 1024)
        self.assertEqual((self.base / "models/large.bin").stat().st_size, 101 * 1024 * 1024)

    async def test_device_upload_rejects_unconfigured_locations_and_escapes(self):
        query = {"root": "model:loras", "location": self.routes.location_id(self.base / "models"), "filename": "model.bin"}
        for change, status in [({"location": "unknown"}, 400), ({"root": "unknown"}, 403), ({"path": "../escape"}, 403), ({"filename": "../escape.bin"}, 403), ({"filename": "C:\\escape.bin"}, 403)]:
            response = await self.client.post("/comfymobile/v1/upload-file", params={**query, **change}, data=b"model bytes")
            self.assertEqual(response.status, status)
        outside = self.base / "outside"
        outside.mkdir()
        (self.base / "models/link").symlink_to(outside, target_is_directory=True)
        response = await self.client.post("/comfymobile/v1/upload-file", params={**query, "path": "link"}, data=b"model bytes")
        self.assertEqual(response.status, 403)
        self.assertEqual(list(outside.iterdir()), [])

    async def test_cancelled_device_upload_removes_partial_file(self):
        import asyncio
        class InterruptedContent:
            async def iter_chunked(self, size):
                yield b"partial model"
                raise asyncio.CancelledError()
        request = types.SimpleNamespace(query={"root": "model:loras", "location": self.routes.location_id(self.base / "models"), "filename": "partial.bin"}, content=InterruptedContent())
        with self.assertRaises(asyncio.CancelledError):
            await self.routes.upload_file(request)
        self.assertEqual(list((self.base / "models").iterdir()), [])


    async def test_download_routes_locations_jobs_and_ownership(self):
        from unittest.mock import AsyncMock, patch
        extra = self.base / "extra"
        (extra / "nested").mkdir(parents=True)
        self.routes.folder_paths.folder_names_and_paths["loras"] = ([str(self.base / "models"), str(extra)], {".bin"})
        response = await self.client.get("/comfymobile/v1/downloads/locations?root=model:loras&path=nested")
        value = await response.json()
        self.assertEqual(value["defaultLocation"], value["destinations"][1]["id"])
        response = await self.client.post("/comfymobile/v1/downloads", json={"url": "file:///tmp/a", "root": "model:loras"})
        self.assertEqual(response.status, 400)
        response = await self.client.post("/comfymobile/v1/downloads", json={"url": "https://example.com/a", "root": "model:loras", "path": "../outside"})
        self.assertEqual(response.status, 403)
        response = await self.client.post("/comfymobile/v1/downloads", json={"url": "https://example.com/a", "root": "model:loras", "location": "99"})
        self.assertEqual(response.status, 400)
        with patch("comfymobile_bridge.downloads.DownloadManager.run", AsyncMock()):
            response = await self.client.post("/comfymobile/v1/downloads", json={"url": "https://example.com/a?token=secret", "key": "secret", "root": "model:loras", "location": value["defaultLocation"], "path": "nested"})
            self.assertEqual(response.status, 202)
            job = await response.json()
            self.assertNotIn("secret", str(job))
            ident = job["id"]
            listing = await (await self.client.get("/comfymobile/v1/downloads")).json()
            self.assertEqual(len(listing), 1)
            response = await self.client.get("/comfymobile/v1/downloads/" + ident)
            self.assertEqual(response.status, 200)
            manager = self.client.app[self.routes.DOWNLOAD_MANAGER_KEY]
            manager.jobs[ident]["state"] = "failed"
            response = await self.client.post("/comfymobile/v1/downloads/" + ident + "/retry", json={})
            self.assertEqual(response.status, 202)
            manager.jobs[ident]["owner"] = "another-user"
            response = await self.client.get("/comfymobile/v1/downloads/" + ident)
            self.assertEqual(response.status, 404)
            response = await self.client.post("/comfymobile/v1/downloads/" + ident + "/cancel", json={})
            self.assertEqual(response.status, 404)


    async def test_download_runs_after_start_request_finishes(self):
        import asyncio
        from aiohttp import ClientSession
        (self.base / "input" / "source.bin").write_bytes(b"downloaded on server")
        response = await self.client.post("/comfymobile/v1/downloads", json={
            "root": "model:loras", "path": "nested", "filename": "model.bin",
            "url": str(self.client.make_url("/comfymobile/v1/content?root=input&path=source.bin")),
        })
        self.assertEqual(response.status, 202)
        job = await response.json()
        response.release()
        manager = self.client.app[self.routes.DOWNLOAD_MANAGER_KEY]
        task = manager.tasks.get(job["id"])
        if task:
            await asyncio.wait_for(task, 5)
        # A new connection sees the existing server-owned job.
        async with ClientSession() as reconnected:
            async with reconnected.get(str(self.client.make_url("/comfymobile/v1/downloads/" + job["id"]))) as result:
                final = await result.json()
        self.assertEqual(final["state"], "completed")
        self.assertEqual((self.base / "models/nested/model.bin").read_bytes(), b"downloaded on server")


if __name__ == "__main__":
    unittest.main()
