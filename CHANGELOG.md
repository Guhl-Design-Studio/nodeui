# NodeUI companion releases

## 2.1.2 — November 17, 2026

- **Android + iOS** — Large folders load more efficiently. The companion reads detailed file metadata only for entries on the requested page.
- **Android + iOS** — Uploads appear under their final filenames only after the transfer completes. Concurrent transfers with the same filename receive separate names.

## 2.1.1 — November 17, 2026

- **Android + iOS:** Add Shared Input, Prompt Input, and Return Image to NodeUI for share-sheet and shortcut workflows, with ordered images and receipt-based results.
- **Android + iOS:** Add per-image browser Upload, Select, Remove, and drop targets while preserving numbered assignments and original dimensions.
- **Android + iOS:** Omit unfilled image processing branches, including grouped scale nodes, without changing saved workflows.
- **Android + iOS:** Forward progress and previews for jobs started by other clients to opted-in NodeUI connections.
- **Android + iOS:** Package and validate all 12 runtime files, preserving both API namespaces and existing transfer tools.

## 2.0.1 — November 3, 2026

- Restore `/comfymobile/v1` as direct aliases for all `/nodeui/v1` endpoints so existing mobile builds keep working, including uploads and downloads. Both namespaces share handlers, access checks, and jobs.
- Keep the renamed `nodeui_bridge` package and archive.

## 2.0.0 — November 3, 2026

- Rename the Python package and ZIP to `nodeui_bridge`.
- Rename all companion routes to `/nodeui/v1` and temporary files to `.nodeui-*`.
- Update Windows and macOS installers, tests, and setup guides. Installers preserve the previous package outside `custom_nodes` to prevent duplicate loading.
- Update NodeUI clients together with this companion; 1.x API routes have been removed.
