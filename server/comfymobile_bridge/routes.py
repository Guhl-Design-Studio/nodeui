"""Versioned ComfyUI routes; no additional server process or port is required."""
from __future__ import annotations

import asyncio
from functools import wraps
import io
import logging
import mimetypes
import os
from pathlib import Path
import tempfile
import hashlib
import aiohttp
from .downloads import DownloadManager, checked_url, discover, provider

from aiohttp import web
import folder_paths
from server import PromptServer

from .filesystem import relative_parts, FileAccessError, Root, copy_to_input, file_info, list_files, resolve, unique_destination, write_upload

API_VERSION = 1
PREFIX = "/comfymobile/v1"
routes = PromptServer.instance.routes


def roots_for(request) -> dict[str, Root]:
    values = [
        Root("input", "Inputs", "input", Path(folder_paths.get_input_directory()), True),
        Root("output", "Outputs", "output", Path(folder_paths.get_output_directory())),
        Root("temp", "Temporary", "temp", Path(folder_paths.get_temp_directory())),
    ]
    manager = PromptServer.instance.user_manager
    workflows = manager.get_request_user_filepath(request, "workflows", create_dir=False)
    if workflows:
        values.insert(0, Root("workflows", "Workflows", "workflows", Path(workflows), True))
    for category, configuration in sorted(folder_paths.folder_names_and_paths.items()):
        if category in {"custom_nodes", "configs"}:
            continue
        # Model categories may search several directories, including aliases and
        # missing optional locations. Present one merged folder per category.
        directories = [Path(directory) for directory in configuration[0] if Path(directory).is_dir()]
        if directories:
            values.append(Root(f"model:{category}", category.replace("_", " ").title(), "models", directories[0], additional_paths=tuple(directories[1:])))
    return {value.id: value for value in values}


def get_root(request, root_id: str | None = None) -> Root:
    root_id = root_id or request.query.get("root", "")
    root = roots_for(request).get(root_id)
    if root is None and root_id.startswith("model:"):
        # Honor already-open browsers from companion 1.0.0 until they refresh.
        category, separator, index = root_id[6:].rpartition(":")
        configuration = folder_paths.folder_names_and_paths.get(category)
        if separator and index.isdecimal() and category not in {"custom_nodes", "configs"} and configuration and int(index) < len(configuration[0]):
            root = Root(root_id, category.replace("_", " ").title(), "models", Path(configuration[0][int(index)]))
    if root is None:
        raise FileAccessError("Unknown ComfyUI folder")
    return root


def guarded(handler):
    @wraps(handler)
    async def wrapped(request):
        try:
            return await handler(request)
        except FileAccessError as error:
            return web.json_response({"error": "invalid_path", "message": str(error)}, status=403)
        except (FileNotFoundError, NotADirectoryError) as error:
            return web.json_response({"error": "not_found", "message": str(error)}, status=404)
        except FileExistsError:
            return web.json_response({"error": "conflict", "message": "A file with this name was uploaded concurrently. Retry."}, status=409)
        except PermissionError:
            return web.json_response({"error": "permission_denied", "message": "ComfyUI cannot access this file."}, status=403)
        except (ValueError, TypeError, KeyError) as error:
            return web.json_response({"error": "invalid_request", "message": str(error)}, status=400)
        except web.HTTPException:
            raise
        except Exception:
            logging.exception("NodeUI companion request failed")
            return web.json_response({"error": "server_error", "message": "The file operation failed. Check the ComfyUI log."}, status=500)
    return wrapped


@routes.get(PREFIX + "/capabilities")
@guarded
async def capabilities(request):
    try:
        from PIL import Image  # noqa: F401
        thumbnails = True
    except ImportError:
        thumbnails = False
    return web.json_response({"apiVersion": API_VERSION, "version": "1.2.0", "downloads": True, "fileUploads": True, "roots": [download_root(root) for root in roots_for(request).values()], "thumbnails": thumbnails, "maxUploadBytes": 100 * 1024 * 1024})


@routes.get(PREFIX + "/files")
@guarded
async def files(request):
    root = get_root(request)
    result = await asyncio.to_thread(list_files, root, request.query.get("path", ""), offset=int(request.query.get("offset", "0")), limit=int(request.query.get("limit", "100")), search=request.query.get("search", ""))
    return web.json_response(result)


@routes.get(PREFIX + "/content")
@guarded
async def content(request):
    file = resolve(get_root(request), request.query.get("path", ""))
    if not file.is_file():
        raise FileAccessError("Select a file to download")
    return web.FileResponse(file, headers={"Content-Disposition": "attachment", "X-Content-Type-Options": "nosniff"})


def make_thumbnail(path: Path, width: int) -> bytes:
    from PIL import Image, ImageOps
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image)
        image.thumbnail((width, width))
        if image.mode not in {"RGB", "L"}:
            background = Image.new("RGB", image.size, (23, 25, 30))
            if image.mode == "RGBA":
                background.paste(image, mask=image.getchannel("A"))
            else:
                background.paste(image.convert("RGB"))
            image = background
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=85)
        return output.getvalue()


@routes.get(PREFIX + "/thumbnail")
@guarded
async def thumbnail(request):
    path = resolve(get_root(request), request.query.get("path", ""))
    if not path.is_file():
        raise FileAccessError("Select an image file")
    if not (mimetypes.guess_type(path.name)[0] or "").startswith("image/"):
        return web.json_response({"error": "unsupported_media", "message": "Thumbnails support image files. Videos play directly in the app."}, status=415)
    try:
        data = await asyncio.to_thread(make_thumbnail, path, max(64, min(1024, int(request.query.get("width", "384")))))
    except ImportError:
        return web.FileResponse(path)
    return web.Response(body=data, content_type="image/jpeg", headers={"Cache-Control": "private, max-age=60"})


@routes.post(PREFIX + "/upload")
@guarded
async def upload(request):
    root = get_root(request)
    if root.kind not in {"input", "workflows"}:
        raise FileAccessError("Uploads are allowed only in Inputs and Workflows")
    reader = await request.multipart()
    part = await reader.next()
    if part is None or not part.filename:
        raise ValueError("A file field is required")
    total = 0
    with tempfile.TemporaryFile() as temporary:
        while chunk := await part.read_chunk():
            total += len(chunk)
            if total > 100 * 1024 * 1024:
                raise web.HTTPRequestEntityTooLarge(max_size=100 * 1024 * 1024, actual_size=total)
            temporary.write(chunk)
        temporary.seek(0)
        info = await asyncio.to_thread(write_upload, root, part.filename, temporary, request.query.get("path", ""))
    return web.json_response(info, status=201)


@routes.post(PREFIX + "/copy")
@guarded
async def copy(request):
    body = await request.json()
    root = get_root(request, body["root"])
    if root.kind not in {"input", "output", "temp"}:
        raise FileAccessError("Only media folders can be reused as inputs")
    result = await asyncio.to_thread(copy_to_input, root, body["path"], get_root(request, "input"))
    return web.json_response({"name": result["name"], "subfolder": str(Path(result["path"]).parent).replace("\\", "/"), "type": "input", "file": result})


def location_id(path):
    return hashlib.sha256(str(path).encode()).hexdigest()[:24]


def download_root(root):
    value = root.public()
    value["downloadDestinations"] = [{"id": location_id(path), "name": str(path)} for path in root.paths]
    return value


def download_owner(request):
    path = PromptServer.instance.user_manager.get_request_user_filepath(request, "workflows", create_dir=False)
    if not path:
        raise FileAccessError("A ComfyUI user is required")
    return hashlib.sha256(str(path).encode()).hexdigest()


@routes.post(PREFIX + "/upload-file")
@guarded
async def upload_file(request):
    """Stream a device file into an explicitly selected configured location."""
    download_owner(request)
    root = get_root(request)
    location = request.query.get("location")
    base = next((path for path in root.paths if location_id(path) == location), None)
    if base is None:
        raise ValueError("Select a valid upload location")
    target = Root(root.id, root.name, root.kind, base, True)
    destination = await asyncio.to_thread(unique_destination, target, request.query.get("filename", ""), request.query.get("path", ""))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".comfymobile-upload-", delete=False) as output:
            temporary = Path(output.name)
            async for chunk in request.content.iter_chunked(1024 * 1024):
                await asyncio.to_thread(output.write, chunk)
            await asyncio.to_thread(output.flush)
        # Publish only a complete transfer, without replacing another file.
        await asyncio.to_thread(os.link, temporary, destination)
        return web.json_response(await asyncio.to_thread(file_info, target, destination), status=201)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


async def close_downloads(app):
    if DOWNLOAD_MANAGER_KEY in app:
        await app[DOWNLOAD_MANAGER_KEY].close()


def download_manager(request):
    return request.app[DOWNLOAD_MANAGER_KEY]


def public_job(job):
    return {key: value for key, value in job.items() if key != "owner"}


@routes.post(PREFIX + "/downloads/resolve")
@guarded
async def resolve_download(request):
    body = await request.json()
    download_owner(request)
    try:
        result = await discover(body["url"], validated_key(body), body.get("folder"), body.get("cursor"))
    except (aiohttp.ClientError, asyncio.TimeoutError):
        raise ValueError("Cannot load provider files. Check the URL, key, and server connection.") from None
    return web.json_response(result)


@routes.post(PREFIX + "/downloads")
@guarded
async def start_download(request):
    body = await request.json()
    root = get_root(request, body["root"])
    location = body.get("location", location_id(root.path))
    selected_path = next((path for path in root.paths if location_id(path) == location), None)
    if selected_path is None:
        raise ValueError("Select a valid download location")
    target = Root(root.id, root.name, root.kind, selected_path, True)
    url = checked_url(body["url"])
    key = validated_key(body) if provider(url) else None
    job = download_manager(request).create(download_owner(request), target, body.get("path", ""), url, key, body.get("filename"))
    job["location"] = location
    return web.json_response(public_job(job), status=202)


@routes.get(PREFIX + "/downloads")
@guarded
async def list_downloads(request):
    return web.json_response([public_job(job) for job in download_manager(request).list(download_owner(request))])


@routes.get(PREFIX + "/downloads/locations")
@guarded
async def download_locations(request):
    root = get_root(request)
    relative = request.query.get("path", "")
    relative_parts(relative)
    preferred = location_id(root.path)
    for base in root.paths:
        try:
            if resolve(Root(root.id, root.name, root.kind, base), relative).is_dir():
                preferred = location_id(base)
                break
        except (FileNotFoundError, FileAccessError):
            continue
    return web.json_response({"destinations": download_root(root)["downloadDestinations"], "defaultLocation": preferred})


@routes.get(PREFIX + "/downloads/{ident}")
@guarded
async def get_download(request):
    jobs = download_manager(request).list(download_owner(request))
    for job in jobs:
        if job["id"] == request.match_info["ident"]:
            return web.json_response(public_job(job))
    raise FileNotFoundError("Download not found")


@routes.post(PREFIX + "/downloads/{ident}/cancel")
@guarded
async def cancel_download(request):
    job = download_manager(request).cancel(request.match_info["ident"], download_owner(request))
    return web.json_response(public_job(job))


@routes.post(PREFIX + "/downloads/{ident}/retry")
@guarded
async def retry_download(request):
    manager = download_manager(request)
    owner = download_owner(request)
    ident = request.match_info["ident"]
    job = manager.jobs.get(ident)
    if not job or job["owner"] != owner:
        raise FileNotFoundError("Download not found")
    if job["state"] not in {"failed", "cancelled"}:
        raise ValueError("Only failed or cancelled downloads can be retried")
    body = await request.json()
    root, path, url, name = manager.sources[ident]
    # Resolve the configured location again so removed/reconfigured roots cannot be written.
    current = get_root(request, root.id)
    if root.path not in current.paths:
        raise FileAccessError("The download location is no longer configured")
    result = manager.create(owner, root, path, url, validated_key(body) if provider(url) else None, name)
    return web.json_response(public_job(result), status=202)


DOWNLOAD_MANAGER_KEY = web.AppKey("comfymobile_downloads", DownloadManager)


def configure_downloads(app):
    app[DOWNLOAD_MANAGER_KEY] = DownloadManager()
    app.on_cleanup.append(close_downloads)


if hasattr(PromptServer.instance, "app"):
    configure_downloads(PromptServer.instance.app)


def validated_key(body):
    key = body.get("key")
    if key is not None and (not isinstance(key, str) or any(ord(c) < 32 for c in key)):
        raise ValueError("Invalid provider key")
    return key
