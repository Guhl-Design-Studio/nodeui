import copy
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nodeui_bridge.share_nodes import SharedInput, shared_image_paths


class SharedImageTests(unittest.TestCase):
    def setUp(self):
        self.pixels = {"a.png": object(), "b.png": object(), "c.png": object()}
        pixels = self.pixels
        self.hashes = {name: name for name in pixels}
        hashes = self.hashes

        class Loader:
            INPUT_TYPES = classmethod(lambda cls: {"required": {"image": (list(pixels), {"image_upload": True})}})
            VALIDATE_INPUTS = classmethod(lambda cls, image: True if image in pixels else "Unreadable image")
            IS_CHANGED = classmethod(lambda cls, image: hashes[image])

            def load_image(self, image):
                return pixels[image], None

        self.modules = patch.dict(sys.modules, {"nodes": types.SimpleNamespace(LoadImage=Loader)})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def test_order_duplicates_and_legacy_prompt_slot(self):
        for paths in [["a.png"], ["c.png", "a.png", "b.png"], ["b.png", "b.png", "a.png"]]:
            result = SharedInput().read(paths[0], "Two lines\n🌲", json.dumps(paths))
            self.assertIs(result[0], self.pixels[paths[0]])
            self.assertEqual(result[1], "Two lines\n🌲")
            self.assertEqual(list(result[2:]), [self.pixels[path] for path in paths[1:]])
        self.assertEqual(SharedInput().read("a.png", "legacy"), (self.pixels["a.png"], "legacy"))
        self.assertEqual(json.loads(json.dumps(SharedInput.RETURN_TYPES)), ["IMAGE", "STRING"])
        self.assertEqual(SharedInput.RETURN_TYPES[1], "STRING")
        self.assertEqual(SharedInput.RETURN_TYPES[50], "IMAGE")

    def test_cache_tracks_all_contents_order_duplicates_and_prompt(self):
        paths = json.dumps(["a.png", "b.png", "c.png"])
        initial = SharedInput.IS_CHANGED("a.png", "prompt", paths)
        self.hashes["c.png"] = "changed contents"
        self.assertNotEqual(initial, SharedInput.IS_CHANGED("a.png", "prompt", paths))
        self.assertNotEqual(initial, SharedInput.IS_CHANGED("c.png", "prompt", json.dumps(["c.png", "b.png", "a.png"])))
        self.assertNotEqual(initial, SharedInput.IS_CHANGED("a.png", "new prompt", paths))
        self.assertNotEqual(SharedInput.IS_CHANGED("a.png", ""), SharedInput.IS_CHANGED("a.png", "", '["a.png","a.png"]'))

    def test_removed_images_leave_holes_without_shifting_other_outputs(self):
        paths = '[null,"b.png",null,"c.png"]'
        self.assertIs(SharedInput.VALIDATE_INPUTS("", paths), True)
        result = SharedInput().read("", "prompt", paths)
        self.assertEqual(result[:2], (None, "prompt"))
        self.assertIs(result[2], self.pixels["b.png"])
        self.assertIsNone(result[3])
        self.assertIs(result[4], self.pixels["c.png"])
        self.assertNotEqual(SharedInput.IS_CHANGED("", "", paths), SharedInput.IS_CHANGED("", "", '[null,null,null,"c.png"]'))

    def test_invalid_or_unreadable_paths_fail_validation(self):
        for value in ["{", "[]", "null", '"a.png"', '[1]', '[""]', '["b.png"]']:
            with self.subTest(value=value):
                self.assertIsNot(SharedInput.VALIDATE_INPUTS("a.png", value), True)
        self.assertIsNot(SharedInput.VALIDATE_INPUTS("a.png", '["a.png","missing.png"]'), True)
        self.assertIs(SharedInput.VALIDATE_INPUTS("a.png", '["a.png","b.png"]'), True)
        self.assertEqual(shared_image_paths("a.png"), ["a.png"])
        for image in ["", None, 1]:
            self.assertIsNot(SharedInput.VALIDATE_INPUTS(image), True)


try:
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    from nodeui_bridge.shared_images import prepare_shared_images, shared_images_middleware
except ImportError:
    web = None


@unittest.skipUnless(web, "Requires aiohttp")
class SharedImageSubmissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        class Consumer:
            OUTPUT_NODE = True
            INPUT_TYPES = classmethod(lambda cls: {"required": {"image1": ("IMAGE",)}, "optional": {"image2": ("IMAGE",), "image3": ("IMAGE",)}})
        class Scale:
            INPUT_TYPES = classmethod(lambda cls: {"required": {"image": ("IMAGE",)}})
        class Lazy:
            INPUT_TYPES = classmethod(lambda cls: {"required": {"image": ("IMAGE", {"lazy": True})}})
        self.modules = patch.dict(sys.modules, {"nodes": types.SimpleNamespace(NODE_CLASS_MAPPINGS={"Consumer": Consumer, "Scale": Scale, "Lazy": Lazy})})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.accepted = []
        async def queue(request):
            body = await request.json()
            self.accepted.append(body)
            return web.json_response(body)
        app = web.Application(middlewares=[shared_images_middleware])
        for path in ["/prompt", "/api/prompt", "/nodeui/v1/share/runs", "/comfymobile/v1/share/runs"]:
            app.router.add_post(path, queue)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    def body(self, paths=None):
        return {"prompt": {"1": {"class_type": "NodeUISharedInput", "inputs": {
            "image": "a.png", "prompt": "text", "image_paths": json.dumps(paths or ["a.png"])}},
            "2": {"class_type": "Consumer", "inputs": {"image1": ["1", 0], "image2": ["1", 2], "image3": ["1", 3], "prompt": ["1", 1]}}},
            "extra_data": {"extra_pnginfo": {"workflow": {"opaque": "keep saved wiring"}}}}

    async def test_optional_unfilled_wires_are_removed_in_all_namespaces(self):
        for path in ["/prompt", "/api/prompt", "/nodeui/v1/share/runs", "/comfymobile/v1/share/runs"]:
            body = self.body()
            original = copy.deepcopy(body)
            prepared = prepare_shared_images(body)
            self.assertEqual(body, original)
            self.assertEqual(prepared["extra_data"], original["extra_data"])
            response = await self.client.post(path, json=body)
            self.assertEqual(response.status, 200)
            actual = (await response.json())["prompt"]["2"]["inputs"]
            self.assertEqual(actual, {"image1": ["1", 0], "prompt": ["1", 1]})

    async def test_supplied_outputs_keep_their_indices(self):
        response = await self.client.post("/prompt", json=self.body(["a.png", "b.png"]))
        inputs = (await response.json())["prompt"]["2"]["inputs"]
        self.assertEqual(inputs["image2"], ["1", 2])
        self.assertNotIn("image3", inputs)

    async def test_unused_processing_branches_are_omitted_before_queue(self):
        for paths in [["a.png"], ["a.png", None, "c.png"], ["a.png", "b.png", "c.png"]]:
            for path in ["/prompt", "/api/prompt", "/nodeui/v1/share/runs", "/comfymobile/v1/share/runs"]:
                body = self.body(paths)
                # Put the consumers first to exercise propagation across passes.
                body["prompt"]["2"]["inputs"]["image2"] = ["scaled-again", 0]
                body["prompt"]["scaled-again"] = {"class_type": "Scale", "inputs": {"image": ["scaled", 0]}}
                body["prompt"]["scaled"] = {"class_type": "Scale", "inputs": {"image": ["1", 2]}}
                body["prompt"]["lazy"] = {"class_type": "Lazy", "inputs": {"image": ["scaled-again", 0]}}
                original = copy.deepcopy(body)
                response = await self.client.post(path, json=body)
                self.assertEqual(response.status, 200)
                actual = (await response.json())["prompt"]
                if len(paths) > 1 and paths[1] is not None:
                    self.assertIn("scaled", actual)
                    self.assertIn("scaled-again", actual)
                    self.assertEqual(actual["2"]["inputs"]["image2"], ["scaled-again", 0])
                    self.assertIn("image", actual["lazy"]["inputs"])
                else:
                    self.assertNotIn("scaled", actual)
                    self.assertNotIn("scaled-again", actual)
                    self.assertNotIn("image2", actual["2"]["inputs"])
                    self.assertEqual(actual["lazy"]["inputs"], {})
                self.assertEqual(actual["2"]["inputs"]["image1"], ["1", 0])
                if len(paths) == 3:
                    self.assertEqual(actual["2"]["inputs"]["image3"], ["1", 3])
                self.assertEqual(body, original)

    async def test_missing_required_output_after_processing_rejects_before_queue(self):
        body = self.body()
        body["prompt"]["2"]["inputs"]["image1"] = ["scale", 0]
        body["prompt"]["scale"] = {"class_type": "Scale", "inputs": {"image": ["1", 2]}}
        response = await self.client.post("/prompt", json=body)
        self.assertEqual(response.status, 400)
        self.assertIn("required image1", (await response.json())["message"])
        self.assertEqual(self.accepted, [])

    async def test_missing_required_image_rejects_before_queue(self):
        body = self.body()
        body["prompt"]["2"]["inputs"]["image1"] = ["1", 2]
        response = await self.client.post("/nodeui/v1/share/runs", json=body)
        self.assertEqual(response.status, 400)
        self.assertIn("required image1", (await response.json())["message"])
        self.assertEqual(self.accepted, [])

    async def test_removed_middle_image_omits_only_that_optional_connection(self):
        body = self.body(["a.png", None, "c.png"])
        response = await self.client.post("/prompt", json=body)
        self.assertEqual(response.status, 200)
        values = (await response.json())["prompt"]["2"]["inputs"]
        self.assertNotIn("image2", values)
        self.assertEqual(values["image3"], ["1", 3])

    async def test_removed_first_required_image_rejects_before_queue(self):
        body = self.body([None, "b.png"])
        body["prompt"]["1"]["inputs"]["image"] = ""
        response = await self.client.post("/prompt", json=body)
        self.assertEqual(response.status, 400)
        self.assertEqual(self.accepted, [])

    async def test_invalid_manifest_rejects_before_queue(self):
        body = self.body()
        body["prompt"]["1"]["inputs"]["image_paths"] = "[]"
        response = await self.client.post("/prompt", json=body)
        self.assertEqual(response.status, 400)
        self.assertEqual(self.accepted, [])

    async def test_malformed_submissions_reject_before_queue(self):
        for body in [[], {"prompt": {"1": {"class_type": "NodeUISharedInput", "inputs": []}}}]:
            response = await self.client.post("/prompt", json=body)
            self.assertEqual(response.status, 400)
        self.assertEqual(self.accepted, [])

    async def test_unrelated_prompts_are_untouched(self):
        body = {"prompt": {"1": {"class_type": "Consumer", "inputs": {"image1": ["other", 3]}}}}
        self.assertIs(prepare_shared_images(body), body)
        response = await self.client.post("/prompt", json=body)
        self.assertEqual(await response.json(), body)
