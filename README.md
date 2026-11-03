# NodeUI server helpers

Companion extension, installers, and technical help for an existing ComfyUI server.

This public repository contains the companion source, installation guides, and release downloads. A GitHub account is not required to read the guides or download release assets.

- [Download the companion ZIP and Windows/macOS installers](https://github.com/Guhl-Design-Studio/nodeui/releases/latest)
- [Install, update, verify, or remove the companion](docs/companion.md)
- [Connection setup, controls, and troubleshooting](docs/technical-help.md)
- [Companion API reference](server/README.md)

Download `nodeui_bridge.zip` and the installer for your computer into the same folder. GitHub's automatic “Source code” archives are repository snapshots; use the named companion ZIP for installation.

## Helper maintenance

The companion uses ComfyUI's existing server and port. Its runtime lives in `server/nodeui_bridge/`; the installers live in `distribution/`.

Run the existing companion tests from the repository root:

```sh
python3 -m unittest discover -s server/tests -v
```

HTTP and transfer tests require `aiohttp` and Pillow in the test interpreter. ComfyUI normally includes these dependencies. Filesystem tests use Python's standard library.

Build the installable archive after changing companion runtime files:

```sh
python3 scripts/package_companion.py
```

The archive contains only `__init__.py`, `filesystem.py`, `routes.py`, `downloads.py`, `resources.py`, `resource_gpu.py`, and `resource_windows.py` under `nodeui_bridge/`. Publish that ZIP and both installers together as release assets. Keep this repository limited to companion helpers and technical documentation.
