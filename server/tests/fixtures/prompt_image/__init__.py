"""Model-free image source for disposable Control Center/Shortcuts tests only.

Copy this folder into a disposable ComfyUI's custom_nodes directory. It is never
included in the companion archive or installed on a user's ComfyUI server.
"""
import hashlib


class PromptTestImage:
    CATEGORY = "NodeUI Tests"
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "render"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"text": ("STRING", {"forceInput": True})}}

    def render(self, text):
        import torch
        rgb = [value / 255 for value in hashlib.sha256(text.encode()).digest()[:3]]
        return (torch.tensor(rgb).reshape(1, 1, 1, 3).repeat(1, 8, 8, 1),)


NODE_CLASS_MAPPINGS = {"NodeUIPromptTestImage": PromptTestImage}
