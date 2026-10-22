"""Portable, scoped filesystem operations, deliberately independent of ComfyUI."""
from __future__ import annotations

from dataclasses import dataclass
import mimetypes
import os
from pathlib import Path, PureWindowsPath
import shutil
import tempfile
from typing import BinaryIO


class FileAccessError(ValueError):
    pass


@dataclass(frozen=True)
class Root:
    id: str
    name: str
    kind: str
    path: Path
    writable: bool = False
    additional_paths: tuple[Path, ...] = ()

    def __post_init__(self):
        paths = []
        for candidate in (self.path, *self.additional_paths):
            candidate = candidate.resolve()
            if any(candidate == previous or (candidate.exists() and previous.exists() and candidate.samefile(previous)) for previous in paths):
                continue
            paths.append(candidate)
        object.__setattr__(self, "path", paths[0])
        object.__setattr__(self, "additional_paths", tuple(paths[1:]))
        if self.writable and self.additional_paths:
            raise ValueError("Writable folders must have a single location")

    @property
    def paths(self) -> tuple[Path, ...]:
        return (self.path, *self.additional_paths)

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "kind": self.kind, "writable": self.writable}


def relative_parts(relative: str) -> tuple[str, ...]:
    """Accept slash-separated logical paths, rejecting absolute Windows/POSIX syntax."""
    if not isinstance(relative, str) or "\x00" in relative:
        raise FileAccessError("Invalid relative path")
    windows = PureWindowsPath(relative)
    normalized = relative.replace("\\", "/")
    if windows.drive or windows.root or normalized.startswith("/"):
        raise FileAccessError("Absolute paths are not allowed")
    parts = tuple(part for part in normalized.split("/") if part not in {"", "."})
    if any(part == ".." or ":" in part for part in parts):
        raise FileAccessError("Path must remain inside its selected folder")
    return parts


def _resolve_in(base: Path, relative: str) -> Path:
    destination = base.joinpath(*relative_parts(relative)).resolve()
    try:
        destination.relative_to(base)
    except ValueError as error:
        raise FileAccessError("Path leaves its selected folder") from error
    return destination


def resolve(root: Root, relative: str = "", *, must_exist: bool = True) -> Path:
    # ComfyUI searches model locations in order. A duplicate relative filename
    # therefore resolves to the first location, including in merged listings.
    for base in root.paths:
        destination = _resolve_in(base, relative)
        if not must_exist or destination.exists():
            return destination
    raise FileNotFoundError("File or folder no longer exists")


def file_info(root: Root, path: Path) -> dict:
    # Resolve before stat so an outward-pointing symlink never exposes target metadata.
    canonical = resolve(root, path.relative_to(root.path).as_posix())
    stat = canonical.stat()
    return {
        "root": root.id,
        "path": path.relative_to(root.path).as_posix(),
        "name": path.name,
        "isDirectory": canonical.is_dir(),
        "size": 0 if canonical.is_dir() else stat.st_size,
        "modified": stat.st_mtime,
        "mimeType": "inode/directory" if canonical.is_dir() else (mimetypes.guess_type(path.name)[0] or "application/octet-stream"),
    }


def list_files(root: Root, relative: str = "", *, offset: int = 0, limit: int = 100, search: str = "") -> dict:
    folder = resolve(root, relative)
    if not folder.is_dir():
        raise NotADirectoryError("Selected path is not a folder")
    entries = []
    seen = set()
    for base in root.paths:
        try:
            location = _resolve_in(base, relative)
        except FileAccessError:
            # The winning folder is already validated above. An unsafe alias
            # in a later location must not expose its contents.
            continue
        if not location.is_dir():
            continue
        scope = Root(root.id, root.name, root.kind, base)
        for path in location.iterdir():
            key = os.path.normcase(path.name)
            if path.name.startswith(".") or key in seen:
                continue
            # Reserve names before filtering so later locations cannot replace
            # an inaccessible entry or change the first location's precedence.
            seen.add(key)
            if search and search.casefold() not in path.name.casefold():
                continue
            try:
                entries.append(file_info(scope, path))
            except (FileAccessError, FileNotFoundError, PermissionError):
                continue
    entries.sort(key=lambda value: (not value["isDirectory"], value["name"].casefold(), value["name"]))
    offset = max(0, offset)
    limit = max(1, min(500, limit))
    end = min(offset + limit, len(entries))
    return {"entries": entries[offset:end], "total": len(entries), "nextOffset": end if end < len(entries) else None}


def unique_destination(root: Root, filename: str, subfolder: str = "") -> Path:
    if not root.writable:
        raise FileAccessError("This folder is read-only")
    parts = relative_parts(filename)
    if len(parts) != 1 or filename in {"", ".", ".."}:
        raise FileAccessError("Upload requires a plain filename")
    folder = resolve(root, subfolder, must_exist=False)
    folder.mkdir(parents=True, exist_ok=True)
    stem, extension = Path(parts[0]).stem, Path(parts[0]).suffix
    candidate = folder / parts[0]
    counter = 1
    while candidate.exists():
        candidate = folder / f"{stem}_{counter}{extension}"
        counter += 1
    # Validate again after folder creation, including any existing symlinks.
    return resolve(root, candidate.relative_to(root.path.resolve()).as_posix(), must_exist=False)


def write_upload(root: Root, filename: str, source: BinaryIO, subfolder: str = "", max_bytes: int = 100 * 1024 * 1024) -> dict:
    destination = unique_destination(root, filename, subfolder)
    temporary = None
    created = False
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".comfymobile-", delete=False) as output:
            temporary = Path(output.name)
            total = 0
            while chunk := source.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise FileAccessError("File exceeds the server upload limit")
                output.write(chunk)
        # Reserve the destination without clobbering another upload's result.
        with destination.open("xb") as output:
            created = True
            with temporary.open("rb") as input_file:
                shutil.copyfileobj(input_file, output)
        return file_info(root, destination)
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def copy_to_input(source_root: Root, relative: str, input_root: Root, subfolder: str = "ComfyMobile") -> dict:
    source = resolve(source_root, relative)
    if not source.is_file():
        raise FileAccessError("Only files can be reused as inputs")
    with source.open("rb") as stream:
        return write_upload(input_root, source.name, stream, subfolder, max_bytes=max(source.stat().st_size, 1))
