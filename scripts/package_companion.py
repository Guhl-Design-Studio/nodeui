#!/usr/bin/env python3
"""Produce the installable companion archive from an explicit runtime allowlist."""
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
destination = root / "distribution" / "nodeui_bridge.zip"
runtime_files = ("__init__.py", "filesystem.py", "routes.py", "downloads.py", "resources.py", "resource_gpu.py", "resource_windows.py")
destination.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for name in runtime_files:
        source = root / "server" / "nodeui_bridge" / name
        archive.write(source, f"nodeui_bridge/{name}")
print(destination)
