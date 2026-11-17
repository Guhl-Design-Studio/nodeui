"""Model-free image-slot inspection, installed only on disposable test servers."""

import asyncio
import json
from aiohttp import web
from server import PromptServer

state = {"mode": "normal", "uploads": 0, "submissions": 0}
upload_gate = asyncio.Event()


@PromptServer.instance.routes.get("/nodeui-test/shared-images")
async def status(request):
    return web.json_response(state)


@PromptServer.instance.routes.post("/nodeui-test/shared-images")
async def control(request):
    global upload_gate
    upload_gate.set()
    upload_gate = asyncio.Event()
    state.update(mode=(await request.json())["mode"], uploads=0, submissions=0)
    return web.json_response(state)


@web.middleware
async def failure_modes(request, handler):
    if request.method == "POST" and request.path.endswith("/share/runs"):
        state["submissions"] += 1
    if request.method == "POST" and request.path in {"/nodeui/v1/upload", "/nodeui/v1/upload-file", "/upload/image"}:
        state["uploads"] += 1
        if state["mode"] == "upload_failure":
            return web.json_response({"message": "Fixture upload failed"}, status=503)
        if state["mode"] == "slow_upload":
            await upload_gate.wait()
            return web.json_response({"message": "Fixture upload cancelled"}, status=503)
    response = await handler(request)
    if request.path == "/nodeui/v1/capabilities" and state["mode"] == "old_companion":
        body = json.loads(response.body)
        body.pop("sharedWorkflowImageOutputs", None)
        return web.json_response(body)
    return response


PromptServer.instance.app.middlewares.append(failure_modes)


class SharedImageInspector:
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "inspect"
    CATEGORY = "NodeUI Tests"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image1": ("IMAGE",)},
                "optional": {"image2": ("IMAGE",), "image3": ("IMAGE",)}}

    def inspect(self, image1, image2=None, image3=None):
        samples = []
        for image in [image1, image2, image3]:
            samples.append(None if image is None else {
                "width": image.shape[2], "height": image.shape[1],
                "rgb": [round(float(channel) * 255) for channel in image[0, 0, 0, :3]],
            })
        return {"ui": {"nodeui_inputs": samples}, "result": (image1,)}


NODE_CLASS_MAPPINGS = {"NodeUISharedImageInspector": SharedImageInspector}
