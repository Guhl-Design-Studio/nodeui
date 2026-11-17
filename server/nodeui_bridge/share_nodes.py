"""ComfyUI nodes shared by the web editor and the NodeUI client."""

import json


class ImageOutputTypes(tuple):
    """Advertise the original slots; appended slots always carry IMAGEs."""
    def __getitem__(self, index):
        if isinstance(index, int) and index >= 2:
            return "IMAGE"
        return super().__getitem__(index)


def shared_image_paths(image, image_paths=""):
    if not image_paths:
        if not isinstance(image, str) or not image:
            raise ValueError("Shared Input needs a readable first image.")
        return [image]
    try:
        paths = json.loads(image_paths)
    except (ValueError, TypeError):
        raise ValueError("Shared Input image paths must be an ordered list of images.") from None
    if not isinstance(paths, list) or not paths or any(p is not None and (not isinstance(p, str) or not p) for p in paths):
        raise ValueError("Shared Input needs an ordered list of image paths or empty slots.")
    if paths[0] is not None and paths[0] != image:
        raise ValueError("Shared Input image 1 must match the first selected image.")
    return paths


class SharedInput:
    CATEGORY = "NodeUI"
    RETURN_TYPES = ImageOutputTypes(("IMAGE", "STRING"))
    RETURN_NAMES = ("image 1", "prompt")
    FUNCTION = "read"

    @classmethod
    def INPUT_TYPES(cls):
        from nodes import LoadImage
        return {"required": {"image": LoadImage.INPUT_TYPES()["required"]["image"],
                             "prompt": ("STRING", {"default": "", "multiline": True})},
                "optional": {"image_paths": ("STRING", {"default": "", "nodeui_internal": True})}}

    @classmethod
    def VALIDATE_INPUTS(cls, image, image_paths=""):
        from nodes import LoadImage
        try:
            paths = shared_image_paths(image, image_paths)
        except ValueError as error:
            return str(error)
        for path in paths:
            if path is None:
                continue
            valid = LoadImage.VALIDATE_INPUTS(path)
            if valid is not True:
                return str(valid)
        return True

    @classmethod
    def IS_CHANGED(cls, image, prompt, image_paths=""):
        from nodes import LoadImage
        return (tuple(LoadImage.IS_CHANGED(path) if path else None for path in shared_image_paths(image, image_paths)), prompt)

    def read(self, image, prompt, image_paths=""):
        from nodes import LoadImage
        pixels = [LoadImage().load_image(path)[0] if path else None for path in shared_image_paths(image, image_paths)]
        return (pixels[0], prompt, *pixels[1:])


class PromptInput:
    CATEGORY = "NodeUI"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    FUNCTION = "read"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"prompt": ("STRING", {"default": "", "multiline": True})}}

    def read(self, prompt):
        return (prompt,)


class ReturnImage:
    CATEGORY = "NodeUI"
    RETURN_TYPES = ()
    FUNCTION = "save"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",)},
                "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"}}

    def save(self, images, prompt=None, extra_pnginfo=None):
        from nodes import SaveImage
        return SaveImage().save_images(images, filename_prefix="NodeUI/Shared",
                                       prompt=prompt, extra_pnginfo=extra_pnginfo)
