"""Portable, scoped filesystem operations, deliberately independent of ComfyUI."""
from __future__ import annotations

from dataclasses import dataclass
import ctypes
import errno
import mimetypes
import os
from pathlib import Path, PureWindowsPath
import stat
import tempfile
import sys
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
    metadata = canonical.stat()
    directory = stat.S_ISDIR(metadata.st_mode)
    return {
        "root": root.id,
        "path": path.relative_to(root.path).as_posix(),
        "name": path.name,
        "isDirectory": directory,
        "size": 0 if directory else metadata.st_size,
        "modified": metadata.st_mtime,
        "mimeType": "inode/directory" if directory else (mimetypes.guess_type(path.name)[0] or "application/octet-stream"),
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
        with os.scandir(location) as children:
            for child in children:
                key = os.path.normcase(child.name)
                if child.name.startswith(".") or key in seen:
                    continue
                # The first location owns the name even if the entry is inaccessible.
                seen.add(key)
                if search and search.casefold() not in child.name.casefold():
                    continue
                try:
                    # On Windows scandir carries the reparse attributes from directory enumeration.
                    reparse = os.name == "nt" and child.stat(follow_symlinks=False).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
                    if child.is_symlink() or reparse or ":" in child.name or "\\" in child.name:
                        resolved = resolve(scope, Path(child.path).relative_to(base).as_posix())
                        is_directory = resolved.is_dir()
                    else:
                        is_directory = child.is_dir(follow_symlinks=False)
                    entries.append((not is_directory, child.name.casefold(), child.name, scope, child.path))
                except (FileAccessError, FileNotFoundError, PermissionError):
                    continue
    entries.sort(key=lambda entry: entry[:3])
    offset = max(0, offset)
    limit = max(1, min(500, limit))
    end = min(offset + limit, len(entries))
    page = []
    for _, _, _, scope, path in entries[offset:end]:
        try:
            page.append(file_info(scope, Path(path)))
        except (FileAccessError, FileNotFoundError, PermissionError):
            continue
    return {"entries": page, "total": len(entries), "nextOffset": end if end < len(entries) else None}


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
    while candidate.exists() or candidate.is_symlink():
        candidate = folder / f"{stem}_{counter}{extension}"
        counter += 1
    # Validate again after folder creation, including any existing symlinks.
    return resolve(root, candidate.relative_to(root.path.resolve()).as_posix(), must_exist=False)


def _rename_exclusive(source: Path, destination: Path) -> None:
    """Atomic rename without replacement, including filesystems without hard links."""
    if sys.platform == "win32":
        # Unlike POSIX rename(), Windows rename never replaces an existing file.
        os.rename(source, destination)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename = getattr(libc, "renamex_np", None)
        if rename is None:
            raise OSError(errno.ENOTSUP, "Exclusive rename is unavailable")
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(os.fsencode(source), os.fsencode(destination), 4)  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        rename = getattr(libc, "renameat2", None)
        if rename is None:
            raise OSError(errno.ENOTSUP, "Exclusive rename is unavailable")
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1)  # AT_FDCWD, RENAME_NOREPLACE
    else:
        raise OSError(errno.ENOTSUP, "Exclusive rename is unavailable")
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def publish_file(source: Path, destination: Path) -> None:
    """Publish only a complete file; neither strategy can overwrite an existing name."""
    try:
        os.link(source, destination)
    except OSError as error:
        unsupported = {errno.EPERM, errno.EACCES, errno.EXDEV, errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS}
        if error.errno not in unsupported and getattr(error, "winerror", None) not in {1, 50}:
            raise
        try:
            _rename_exclusive(source, destination)
        except OSError as rename_error:
            if rename_error.errno in {errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS, errno.EINVAL}:
                raise FileAccessError("This destination cannot safely publish files without overwriting. Choose another location.") from None
            raise


def publish_unique(source: Path, root: Root, filename: str, subfolder: str) -> Path:
    while True:
        destination = unique_destination(root, filename, subfolder)
        try:
            publish_file(source, destination)
            return destination
        except FileExistsError:
            continue


def check_publish_support(folder: Path) -> None:
    """Fail before streaming if neither safe publication strategy is supported."""
    with tempfile.NamedTemporaryFile(dir=folder, prefix=".nodeui-probe-", delete=False) as stream:
        source = Path(stream.name)
    destination = source.with_name(source.name + ".published")
    published = False
    try:
        publish_file(source, destination)
        published = True
    finally:
        source.unlink(missing_ok=True)
        if published:
            destination.unlink(missing_ok=True)


def delete_file(root: Root, relative: str) -> None:
    """Delete one file from the same winning location used by merged listings."""
    parts = relative_parts(relative)
    if not parts:
        raise FileAccessError("Select an individual file to delete")
    for base in root.paths:
        target = _resolve_in(base, relative)
        candidate = base.joinpath(*parts)
        if candidate.is_symlink():
            raise FileAccessError("Symbolic links cannot be deleted through the app")
        if not target.exists():
            continue
        if not target.is_file():
            raise FileAccessError("Only individual files can be deleted")
        target.unlink()
        return
    raise FileNotFoundError("The file no longer exists")


def write_upload(root: Root, filename: str, source: BinaryIO, subfolder: str = "", max_bytes: int = 100 * 1024 * 1024) -> dict:
    destination = unique_destination(root, filename, subfolder)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".nodeui-", delete=False) as output:
            temporary = Path(output.name)
            total = 0
            while chunk := source.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise FileAccessError("File exceeds the server upload limit")
                output.write(chunk)
        destination = publish_unique(temporary, root, filename, subfolder)
        return file_info(root, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def copy_to_input(source_root: Root, relative: str, input_root: Root, subfolder: str = "") -> dict:
    source = resolve(source_root, relative)
    if not source.is_file():
        raise FileAccessError("Only files can be reused as inputs")
    with source.open("rb") as stream:
        return write_upload(input_root, source.name, stream, subfolder, max_bytes=max(source.stat().st_size, 1))
