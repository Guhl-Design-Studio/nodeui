"""NodeUI companion. Copy this directory into ComfyUI/custom_nodes/."""

from .share_nodes import SharedInput, PromptInput, ReturnImage

NODE_CLASS_MAPPINGS = {"NodeUISharedInput": SharedInput, "NodeUIPromptInput": PromptInput, "NodeUIReturnImage": ReturnImage}
NODE_DISPLAY_NAME_MAPPINGS = {"NodeUISharedInput": "Shared Input", "NodeUIPromptInput": "Prompt Input", "NodeUIReturnImage": "Return Image to NodeUI"}
WEB_DIRECTORY = "./web"

try:
    from . import routes  # noqa: F401; registers HTTP handlers when ComfyUI imports us
except ModuleNotFoundError as error:
    if error.name not in {"server", "folder_paths", "aiohttp"}:
        raise

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
