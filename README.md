# NodeUI server helpers

Companion extension, installers, and technical help for an existing ComfyUI server.

This repository is private. Sign in with a GitHub account that has repository access to read the guides or download release assets. An account without access may see a 404 page.

- [Download the companion ZIP and Windows/macOS installers](https://github.com/aguhl0614/nodeui/releases/latest)
- [Install, update, verify, or remove the companion](docs/companion.md)
- [Connection setup, controls, and troubleshooting](docs/technical-help.md)
- [Companion API reference](server/README.md)

Download `comfymobile_bridge.zip` and the installer for your computer into the same folder. GitHub's automatic “Source code” archives are repository snapshots; use the named companion ZIP for installation.

## Helper maintenance

The companion uses ComfyUI's existing server and port. Its runtime lives in `server/comfymobile_bridge/`; the installers live in `distribution/`.

Run the existing companion tests from the repository root:

```sh
python3 -m unittest discover -s server/tests -v
```

HTTP and transfer tests require `aiohttp` and Pillow in the test interpreter. ComfyUI normally includes these dependencies. Filesystem tests use Python's standard library.

Build the installable archive after changing companion runtime files:

```sh
python3 scripts/package_companion.py
```

The archive contains only `__init__.py`, `filesystem.py`, `routes.py`, and `downloads.py` under `comfymobile_bridge/`. Publish that ZIP and both installers together as release assets. Keep this repository limited to companion helpers and technical documentation.
