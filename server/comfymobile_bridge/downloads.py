"""Provider discovery and server-owned streaming download jobs."""
from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import time
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit
import uuid

import aiohttp
from .filesystem import FileAccessError, Root, relative_parts, resolve, unique_destination, file_info, publish_file, check_publish_support


def checked_url(value):
    if not isinstance(value, str):
        raise ValueError("Enter an HTTP or HTTPS URL")
    value = value.strip()
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Enter an HTTP or HTTPS URL without embedded credentials")
    return value


def provider(url):
    host = urlsplit(url).hostname
    return "huggingface" if host == "huggingface.co" else "civitai" if host in {"civitai.com", "www.civitai.com"} else None


def filename(value):
    parts = relative_parts(value)
    if len(parts) != 1 or value != parts[0] or value.startswith("."):
        raise ValueError("Enter a plain filename without folders")
    return value


async def fetch(session, url, key=None):
    """Redirect explicitly so a provider token never reaches a storage host."""
    url = checked_url(url)
    origin = urlsplit(url).netloc
    for _ in range(11):
        headers = {}
        if key and urlsplit(url).netloc == origin and provider(url):
            if urlsplit(url).scheme != "https":
                raise ValueError("Provider credentials require HTTPS")
            headers["Authorization"] = "Bearer " + key
        try:
            response = await session.get(url, headers=headers, allow_redirects=False)
        except (aiohttp.ClientError, ValueError, asyncio.TimeoutError):
            raise ValueError("Cannot connect to the download server. Check the URL and try again.") from None
        if response.status in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location")
            response.release()
            if not location:
                raise ValueError("The download redirect has no destination")
            next_url = checked_url(urljoin(url, location))
            if urlsplit(url).scheme == "https" and urlsplit(next_url).scheme != "https":
                raise ValueError("The download redirected to an insecure address")
            url = next_url
            continue
        if response.status >= 400:
            status = response.status
            response.release()
            if status in {401, 403}:
                raise ValueError("Access denied. Check your provider key and accept any required model license on the provider website.")
            raise ValueError(f"The remote server returned HTTP {status}")
        return response
    raise ValueError("Too many download redirects")


async def metadata(session, url, key):
    response = await fetch(session, url, key)
    try:
        return await response.json()
    finally:
        response.release()


async def discover(url, key=None, folder=None, cursor=None):
    url = checked_url(url)
    source = provider(url)
    parts = [unquote(p) for p in urlsplit(url).path.strip("/").split("/")]
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        if source == "huggingface" and len(parts) >= 2:
            offset = 1 if parts[0] in {"datasets", "spaces"} else 0
            if len(parts) < offset + 2:
                raise ValueError("Enter a repository or file URL")
            repo = "/".join(parts[offset:offset+2])
            kind = {"datasets": "datasets", "spaces": "spaces"}.get(parts[0], "models")
            tail = parts[offset+2:]
            prefix = (parts[0] + "/") if offset else ""
            if tail and tail[0] in {"blob", "resolve"}:
                if len(tail) < 3:
                    raise ValueError("The file link is incomplete")
                target = f"https://huggingface.co/{prefix}{repo}/resolve/" + "/".join(quote(p, safe="") for p in tail[1:])
                if urlsplit(url).query:
                    target += "?" + urlsplit(url).query
                return {"files": [{"name": tail[-1], "url": target, "isDirectory": False}], "folder": "", "nextCursor": None}
            revision = tail[1] if len(tail) > 1 and tail[0] == "tree" else "main"
            initial = "/".join(tail[2:]) if tail and tail[0] == "tree" else ""
            selected = initial if folder is None else folder
            relative_parts(selected)
            endpoint = f"https://huggingface.co/api/{kind}/{repo}/tree/{quote(revision, safe='')}"
            if selected:
                endpoint += "/" + quote(selected, safe="/")
            endpoint += "?limit=100"
            if cursor:
                endpoint += "&cursor=" + quote(cursor, safe="")
            response = await fetch(session, endpoint, key)
            try:
                values = await response.json()
                link = response.links.get("next")
                next_cursor = None
                if link:
                    from urllib.parse import parse_qs
                    next_cursor = parse_qs(urlsplit(str(link["url"])).query).get("cursor", [None])[0]
            finally:
                response.release()
            files = []
            for item in values:
                path = item["path"]
                files.append({"name": path, "isDirectory": item["type"] == "directory", "size": item.get("size"), "url": f"https://huggingface.co/{prefix}{repo}/resolve/{quote(revision, safe='')}/{quote(path, safe='/')}"})
            return {"files": files, "folder": selected, "nextCursor": next_cursor}
        if source == "civitai" and parts[0] == "models" and len(parts) > 1:
            from urllib.parse import parse_qs
            version = parse_qs(urlsplit(url).query).get("modelVersionId", [None])[0]
            if not parts[1].isdigit() or (version and not version.isdigit()):
                raise ValueError("Invalid Civitai model or version")
            endpoint = "https://civitai.com/api/v1/" + ("model-versions/" + version if version else "models/" + parts[1])
            value = await metadata(session, endpoint, key)
            versions = [value] if version else value.get("modelVersions", [])
            files = [{"name": f["name"], "url": f["downloadUrl"], "isDirectory": False, "size": int(f.get("sizeKB", 0) * 1024), "version": v.get("name", ""), "format": f.get("metadata", {}).get("format", "")} for v in versions for f in v.get("files", []) if f.get("downloadUrl")]
            return {"files": files, "folder": "", "nextCursor": None}
    return {"files": [{"name": unquote(parts[-1]) or "download", "url": url, "isDirectory": False}], "folder": "", "nextCursor": None}


class DownloadManager:
    def __init__(self):
        self.jobs = {}
        self.tasks = {}
        self.sources = {}
        self.slots = asyncio.Semaphore(2)

    def list(self, owner):
        self.prune()
        return [v.copy() for v in self.jobs.values() if v["owner"] == owner]

    def prune(self):
        for ident, job in list(self.jobs.items()):
            if job["state"] in {"completed", "failed", "cancelled"} and time.time() - job["updated"] > 86400:
                self.jobs.pop(ident, None)
                self.sources.pop(ident, None)

    def create(self, owner, root, path, url, key, name=None):
        checked_url(url)
        relative_parts(path)
        if name:
            filename(name)
        # Validate containment before accepting work; folders may be created later.
        resolve(root, path, must_exist=False)
        ident = str(uuid.uuid4())
        self.jobs[ident] = dict(id=ident, owner=owner, root=root.id, path=path, name=name or "Download", state="queued", receivedBytes=0, totalBytes=None, error=None, updated=time.time())
        self.jobs[ident]["provider"] = provider(url)
        self.sources[ident] = (root, path, url, name)
        self.tasks[ident] = asyncio.create_task(self.run(ident, root, path, url, key, name))
        self.tasks[ident].add_done_callback(lambda task: self.tasks.pop(ident, None))
        return self.jobs[ident].copy()

    def cancel(self, ident, owner):
        if ident not in self.jobs or self.jobs[ident]["owner"] != owner:
            raise FileNotFoundError("Download not found")
        task = self.tasks.get(ident)
        if task:
            self.jobs[ident].update(state="cancelled", updated=time.time())
            task.cancel()
        return self.jobs[ident].copy()

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def run(self, ident, root, path, url, key, name):
        job = self.jobs[ident]
        temporary = None
        try:
            async with self.slots:
                job.update(state="downloading", updated=time.time())
                timeout = aiohttp.ClientTimeout(total=None, connect=60, sock_read=120)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    response = await fetch(session, url, key)
                    try:
                        if response.content_type in {"text/html", "application/xhtml+xml"}:
                            raise ValueError("This URL returned a web page. Use a file download link.")
                        proposed = name or (response.content_disposition.filename if response.content_disposition else None) or unquote(urlsplit(str(response.url)).path.rsplit("/", 1)[-1])
                        proposed = filename(proposed or "download")
                        destination = unique_destination(root, proposed, path)
                        check_publish_support(destination.parent)
                        job.update(name=destination.name, totalBytes=None if response.headers.get("Content-Encoding") else response.content_length)
                        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".comfymobile-download-", delete=False) as output:
                            temporary = Path(output.name)
                            async for chunk in response.content.iter_chunked(1024 * 1024):
                                await asyncio.to_thread(output.write, chunk)
                                job.update(receivedBytes=job["receivedBytes"] + len(chunk), updated=time.time())
                        # Both hard links and exclusive rename publish complete files atomically.
                        while True:
                            destination = unique_destination(root, proposed, path)
                            try:
                                publish_file(temporary, destination)
                                break
                            except FileExistsError:
                                continue
                        info = file_info(root, destination)
                        job.update(state="completed", name=info["name"], path=info["path"], updated=time.time())
                    finally:
                        response.release()
        except asyncio.CancelledError:
            job.update(state="cancelled", updated=time.time())
        except (ValueError, FileAccessError) as error:
            job.update(state="failed", error=str(error), updated=time.time())
        except OSError:
            job.update(state="failed", error="Cannot write the file. Check server disk space and folder permissions.", updated=time.time())
        except Exception:
            job.update(state="failed", error="Download interrupted by a network or remote server error. Retry the download.", updated=time.time())
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
