"""Model-free MP4 output for disposable iOS Shortcuts receiver tests only.

Copy this folder alongside fixtures/prompt_image into a disposable ComfyUI's
custom_nodes. Never package it with the companion or install it in production.
"""
from fractions import Fraction
from pathlib import Path


class TestVideoOutput:
    CATEGORY = "NodeUI Tests"
    RETURN_TYPES = ()
    FUNCTION = "save"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",),
                             "field": (["images", "gifs", "videos"],)}}

    def save(self, images, field):
        import av
        import folder_paths
        import torch

        directory, name, counter, subfolder, _ = folder_paths.get_save_image_path(
            "NodeUI Tests/Shortcut Video", folder_paths.get_output_directory())
        filename = f"{name}_{counter:05}_.mp4"
        with av.open(str(Path(directory) / filename), mode="w") as container:
            stream = container.add_stream("mpeg4", rate=Fraction(8))
            stream.width, stream.height = images.shape[2], images.shape[1]
            stream.pix_fmt = "yuv420p"
            for image in images:
                pixels = (image[:, :, :3].clamp(0, 1) * 255).to(device="cpu", dtype=torch.uint8).numpy()
                frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
        return {"ui": {field: [{"filename": filename, "subfolder": subfolder, "type": "output"}]}}


NODE_CLASS_MAPPINGS = {"NodeUITestVideoOutput": TestVideoOutput}
