# NodeUI companion releases

## 2.0.0 — November 3, 2026

- Rename the Python package and ZIP to `nodeui_bridge`.
- Rename all companion routes to `/nodeui/v1` and temporary files to `.nodeui-*`.
- Update Windows and macOS installers, tests, and setup guides. Installers preserve the previous package outside `custom_nodes` to prevent duplicate loading.
- Update NodeUI clients together with this companion; 1.x API routes have been removed.
