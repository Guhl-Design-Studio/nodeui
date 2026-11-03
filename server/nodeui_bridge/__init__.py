"""NodeUI companion. Copy this directory into ComfyUI/custom_nodes/."""

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

try:
    from . import routes  # noqa: F401; registers HTTP handlers when ComfyUI imports us
except ModuleNotFoundError as error:
    if error.name not in {"server", "folder_paths", "aiohttp"}:
        raise

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
