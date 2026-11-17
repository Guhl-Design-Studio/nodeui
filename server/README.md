# NodeUI companion

This is the server companion for **NodeUI**. Version **2.1.2** uses the `nodeui_bridge` package, `nodeui_bridge.zip` archive, and `/nodeui/v1` API routes. The `/comfymobile/v1` routes remain available as aliases for existing mobile builds. Both namespaces use the same handlers and transfer jobs. Remove the previous companion from `custom_nodes` before restarting.

Copy `nodeui_bridge` into your ComfyUI `custom_nodes` directory and restart ComfyUI once. It registers routes on the same ComfyUI HTTP server and bundles a small browser extension for Shared Input’s growing image outputs. No separate process, credentials, or port is installed.

Windows portable example: `E:\ComfyUI\ComfyUI\custom_nodes\nodeui_bridge`.

macOS example: `<ComfyUI>/custom_nodes/nodeui_bridge`.

Verify with `http://<server>:8188/nodeui/v1/capabilities`. The response reports API version 1, enabled image thumbnails, upload size, and logical folder roots. Pillow is normally present in ComfyUI; when absent, image requests return the original image instead of a thumbnail.

The app still loads, edits and executes workflows without this companion. Its fallback browser uses ComfyUI's workflow/model endpoints and indexed assets; complete filesystem browsing and server-side reuse of outputs require the companion.

## Shared workflows in 2.1.0

The companion registers **Shared Input** and **Return Image to NodeUI** in the NodeUI category. Both work in the browser editor. See the [iOS setup and example](../docs/companion.md#run-a-workflow-from-an-iphone-or-ipad).

The companion advertises `sharedWorkflowImageOutputs: true`. Shared Input grows numbered image connectors as they are wired, preserving the original image/prompt slots and every image’s dimensions. Shortcuts passes ordered uploaded paths through the internal optional `image_paths` input. Missing image outputs and processing branches that require them are omitted before validation. Optional downstream inputs use their normal defaults; missing required output inputs still reject the submission before any job is queued. Saved workflow wiring is preserved. Check the capability rather than the version string alone, since earlier 2.1.0 archives lack multiple-image support.

In the ComfyUI browser, each connected image output has its own preview area and **Upload**, **Select**, and **Remove** buttons. Drop one local image directly into an area to upload it to that numbered slot. **Select** refreshes the server’s uploaded-image list, including uploads from other nodes or devices, and reuses the selected image without uploading it again. ComfyUI image assets and same-server image-preview links can also be dropped into an area. Replacing or removing an image preserves every other numbered assignment; removing a reference keeps the uploaded file on the server. The `web/shared_input.js` asset is included in the installable archive; reload the editor after installing the updated companion.

Browser-extension regressions run with `node --test server/tests/test_shared_input_web.mjs` from the repository root. Companion API tests run with `python -m unittest discover -s server/tests -v` in an environment with aiohttp and Pillow.

**Prompt Input** supplies a text-only input for **Run NodeUI Workflow With Prompt**. Connect it through your image-generation nodes to **Return Image to NodeUI**, then save the workflow to the server. The companion advertises `promptWorkflows: true`; the iOS action binds a new prompt in a submission copy and uses the same receipt/result endpoints without uploading an image. A [Control Center shortcut](../docs/control-center.md) can ask for the prompt in iOS's popup while NodeUI stays in the background.

The capabilities response advertises `sharedWorkflows: true`. `POST /nodeui/v1/share/runs` accepts ComfyUI’s prompt request plus a random UUID in `nodeui_receipt` and the return node ID in `nodeui_output`. Repeating an accepted receipt returns the same job ID. The native prompt handler performs validation and queues the graph. Ordinary web submissions use the normal ComfyUI endpoint.

`GET /nodeui/v1/share/result` takes the receipt in the `X-NodeUI-Receipt` header. It waits for that user's job and returns the first PNG from the designated output, or HTTP 202 to reconnect after a long wait. It reports failed or cancelled runs and missing files. Receipts persist in the ComfyUI system user directory. The complete image batch remains in the normal output folder and execution history.

## API version 1

All file paths are relative to a root reported by capabilities. Root paths are never accepted from the client. Traversal, absolute POSIX/Windows paths and symlinks leaving a configured root are rejected.

| Method | Route | Parameters / body |
| --- | --- | --- |
| GET | `/nodeui/v1/capabilities` | Returns `apiVersion`, `roots`, `thumbnails`, `maxUploadBytes` |
| GET | `/nodeui/v1/resources` | CPU, RAM and primary GPU telemetry; companion 1.4.0+ |
| GET | `/nodeui/v1/files` | `root`, `path`, `offset=0`, `limit=100`, optional `search`; returns `entries`, `total`, `nextOffset` |
| DELETE | `/nodeui/v1/files` | `root`, `path`; deletes one file, returns HTTP 204 (companion 1.3.0+) |
| GET | `/nodeui/v1/content` | `root`, `path`; streams content, supports HTTP Range through aiohttp |
| GET | `/nodeui/v1/thumbnail` | `root`, `path`, optional `width=384` (64–1024); image thumbnails |
| POST | `/nodeui/v1/upload` | `root`, optional `path` query; one multipart file; inputs/workflows only, no overwrite |
| POST | `/nodeui/v1/copy` | JSON `{"root":"output","path":"folder/image.png"}`; copies into the main `input` folder, returns ComfyUI-compatible `name`, `subfolder`, `type` |

The legacy multipart upload route accepts Inputs and Workflows only. Model and output folders use the explicit destination API described below for device uploads and URL downloads. Existing input uploads receive a numeric suffix rather than overwriting. Workflow saving uses ComfyUI's existing userdata endpoint and the app's conflict check. The companion respects ComfyUI's request-user workflow folder.

Companion 1.0.1 presents one model root per category, such as `model:checkpoints`, merging its existing configured locations and nested folders. Repeated physical locations and duplicate relative filenames appear once; the first configured location supplies a duplicate file, matching ComfyUI's search order. Missing model locations are omitted. Older indexed root IDs remain usable until an open browser refreshes its Locations list.

## Tests

Run `python3 -m unittest discover -s server/tests -v` from the repository root. Filesystem tests need only Python's standard library. Route integration tests additionally use aiohttp and Pillow, already included with a usual ComfyUI install.

## Jobs started by another client (companion 2.0.2)

ComfyUI normally directs sampling progress and preview images to the WebSocket client that submitted the job. Updated Android and iOS clients opt in to observing other jobs by sending `nodeui_observe_execution: true` with `supports_preview_metadata: true` in their first WebSocket `feature_flags` message. The companion forwards execution updates as `nodeui_execution` messages containing `type` and `data`, and previews as prompt-scoped binary metadata packets. The submitting client's connection and events are preserved; browser clients that do not opt in receive no additional events. Broadcasts are not duplicated, and legacy frames retain the job identity captured when they were produced.

Capabilities advertise `executionObservation: true` when the ComfyUI transport supports the relay. Install the updated companion archive and restart ComfyUI when its queue is idle, then reconnect the updated Android or iOS app. Older companions cannot forward previews directed to another client. Preview generation still depends on that job's preview settings and sampler; this feature does not enable previews for a job that produces none. It does not apply to Comfy Cloud.

This integration archive retains version **2.1.0** and includes both execution observation and shared workflows. Earlier 2.1.0 archives may lack the relay; check `executionObservation` rather than relying on the version string alone.

## URL downloads (companion 1.1.0)

In NodeUI, open **Settings → Download keys** to save optional Hugging Face and Civitai keys in the device Keychain. Public files need no key. Keys are shared across server profiles on that device and sent to the selected server only when resolving or downloading a matching provider URL. The companion keeps credentials in memory, scopes authorization to the provider host, and strips it when following cross-host redirects. Keys, source URLs and signed storage URLs are excluded from job responses and error messages.

Browse to the destination folder, then choose **File actions → Download from URL**. Paste a direct HTTP/HTTPS file URL, a Hugging Face repository/tree/blob/resolve URL, or a Civitai model page (including `modelVersionId`). Repository pages show folders and paginated files; Civitai pages show the available versions/files. Select one file, optionally enter a filename, and start the download. Restricted files still require a valid key, account access, and any provider license acceptance. Generic webpage scraping and interactive website sign-in are unsupported.

Downloads run on the server, with two concurrent transfers and a queue. They continue when the app is closed, and appear under **File actions → Downloads** after reconnection. Progress includes downloaded bytes and total size when known. Failed/cancelled jobs can be retried with the device's current key. Jobs and retry information remain in memory for up to 24 hours after completion; restarting ComfyUI interrupts running jobs and clears the history. Downloads do not resume across server restarts.

Each root now has a separate `downloadDestinations` array containing server-issued location IDs and display paths. In merged model categories the app lets you choose a physical location, defaulting to the first one containing the browsed subfolder, or the first configured location otherwise. Missing destination subfolders are created. The legacy multipart permissions and merged browsing/search order remain unchanged; model roots still report `writable: false` for that route. Companion 1.2.0 adds a separate device-file upload route using these explicit destinations. Custom-node/configuration locations remain excluded. Display paths are returned for destination selection, but filesystem paths are never accepted from clients.

Files stream to a hidden temporary file on the destination filesystem. Completed files are atomically published using hard links or an exclusive rename, without replacing existing files; duplicate names receive numeric suffixes. Downloads have no 100 MB upload limit. Failed/cancelled transfers remove their temporary files. After an abrupt server/process termination, a hidden `.nodeui-download-*` temporary file may remain and can be removed while the server is stopped.

| Method | Route | Parameters / body |
| --- | --- | --- |
| GET | `/nodeui/v1/capabilities` | Adds `downloads: true`, `version: "1.1.0"`, and root `downloadDestinations` |
| GET | `/nodeui/v1/downloads/locations` | `root`, optional `path`; returns `destinations`, `defaultLocation` |
| POST | `/nodeui/v1/downloads/resolve` | JSON `url`, optional `key`, `folder`, `cursor`; returns `files`, `folder`, `nextCursor`. Omit `folder` for the URL's initial folder; use an empty string for repository root. |
| POST | `/nodeui/v1/downloads` | JSON `url`, `root`, optional `path`, `location`, `filename`, `key`; returns job, HTTP 202 |
| GET | `/nodeui/v1/downloads` | Lists this ComfyUI user's jobs |
| GET | `/nodeui/v1/downloads/{id}` | Returns one owned job |
| POST | `/nodeui/v1/downloads/{id}/cancel` | Cancels an owned job |
| POST | `/nodeui/v1/downloads/{id}/retry` | JSON optional `key`; retries a failed/cancelled job, returns a new job |

Job fields: `id`, `root`, `path`, `name`, `state` (`queued`, `downloading`, `completed`, `failed`, `cancelled`), `receivedBytes`, nullable `totalBytes`, nullable `error`, nullable `provider`, and `updated`. `path` is the destination folder during transfer and the completed relative filename after success. Jobs are scoped using ComfyUI's request-user workflow directory. Older companions omit the added capabilities; the app directs users to update rather than attempting an incompatible fallback.

Local UI fixture: run `scripts/download_test_server.py` using Python with aiohttp installed, then run `DownloadUITests` on an iOS simulator. The fixture uses the actual companion routes and writes only to a temporary folder. Provider discovery and transfer tests use mocked provider responses and local HTTP fixtures, including a 101 MB streamed transfer.


## Device file uploads (companion 1.2.0)

Browse to a model, output or temporary folder and choose **File actions → Upload file**. Confirm the destination location when a model category spans multiple directories, then choose a file using the native Files picker. Uploads start immediately, show the filename and a cancel action, and refresh the browsed folder on completion. Keep NodeUI open until the upload finishes. Inputs retain their existing upload/import flow; Workflows retains JSON import.

Capabilities now advertise `fileUploads: true` and `version: "1.2.0"`. The new `POST /nodeui/v1/upload-file` endpoint accepts the raw file body and query parameters `root`, `path`, `location`, and `filename`. Location IDs come from `/downloads/locations`, including the preferred physical location for the selected subfolder. Unknown locations, path traversal and outward symlinks are rejected. Only configured roots can receive files; the request must resolve to a ComfyUI user. Existing files receive numeric suffixes instead of being replaced.

The app uploads directly from the security-scoped file URL, and the server streams chunks into a hidden temporary file on the destination filesystem. This endpoint has no 100 MB multipart limit. A complete file is published atomically without replacing another file; interrupted or cancelled transfers remove the temporary file. A server/process crash may leave `.nodeui-upload-*` files, which can be removed while ComfyUI is stopped. Uploads run only while the app remains connected; they are separate from the server-owned Downloads queue.

Validation includes a 101 MB streamed device upload, selected secondary model location, duplicate names, rejected paths/locations and cancelled-transfer cleanup. The local fixture on port 18767 also supports `NODEUI_UPLOAD_TEST_SERVER=http://127.0.0.1:18767 swift test --package-path ios/Packages/NodeUINetworking` for a native disk-to-server upload round trip. UI tests verify the model-folder menu, selected destination and native Files picker alongside the existing URL download flow.

## File deletion (companion 1.3.0)

Update the installed companion and restart ComfyUI to enable **File Browser → swipe left → Delete**, or hold a file and choose **Delete file**. The app names the file and server before confirmation. Successful deletion refreshes the current folder; a failed request leaves the file listed and displays the error.

Capabilities advertise `fileDeletion: true`, `version: "1.3.0"`, and `deletable: true` on configured roots. `DELETE /nodeui/v1/files?root=...&path=...` deletes one regular file in Inputs, Outputs, Temporary, the current user's Workflows, or configured model locations. Directory/root deletion, symbolic links, traversal, and paths outside configured roots are rejected. Merged model categories delete only the first matching file shown by browsing; another copy in a later location can appear after refresh. A valid ComfyUI request user is required. A missing file returns 404; permission errors return 403. Existing `writable` permissions continue to describe the legacy upload route.

Saved workflows can also be deleted through ComfyUI's native userdata API without the companion. Cloud input/output assets use the authenticated asset API; Cloud files still in use report the server's refusal. The app does not expose deletion for Cloud model listings that lack an asset ID.

Run `scripts/file_delete_test_server.py` with aiohttp to exercise the real companion against disposable files on loopback port 18785. `FileDeletionUITests` checks cancellation, swipe/context-menu deletion, failed deletion, nested folders, and projected grid landmarks while panning and zooming.

## Resource monitoring (companion 1.4.0)

Capabilities now advertise `resourceMonitoring: true` and `version: "1.4.0"`. `GET /nodeui/v1/resources` returns a Unix-seconds `sampledAt`, nullable `cpuPercent`, `ram: {usedBytes, totalBytes}`, and nullable `gpu: {id, name, utilizationPercent, memoryKind, memory: {usedBytes, totalBytes}}`. Unknown readings are JSON null. Memory values are bytes; utilization values are percentages from 0 to 100. CPU and memory usage describe the whole server. The GPU is ComfyUI's selected primary device rather than an aggregate across adapters.

CPU uses successive system CPU-time samples; its first reading is unavailable while the sampler primes. RAM usage is total minus available memory. `psutil` is already a standard ComfyUI dependency; when it is missing, CPU/RAM readings remain unavailable and the route continues working.

GPU readers use these read-only sources without administrator access or new Python dependencies:

- NVIDIA on Windows/Linux: `nvidia-smi` from the installed driver, matching the selected GPU by UUID/PCI identity. Unknown driver values remain null.
- AMD on Linux: `amdgpu` sysfs utilization and VRAM counters, matching physical PCI identity, including HIP's device-visibility remapping. Missing/unreadable counters remain null.
- AMD on Windows: DXGI adapter identity and WDDM PDH performance counters. Aggregate process contributions per engine, then report the busiest engine. The rate counter needs a second sample before utilization is available. Names are matched only when unique; ambiguous identical adapters remain unavailable rather than reporting another GPU.
- Apple and AMD on macOS: IORegistry accelerator performance counters exposed by the driver. Apple GPU memory is `In use system memory` against total physical RAM, labelled shared memory. It is not a separate VRAM pool and must not be added to RAM usage. AMD dedicated-memory totals can use ComfyUI's memory reader when the OS omits that total.

Driver/OS combinations may omit individual counters. ComfyUI's own GPU-memory readings remain available when a utilization provider fails; MPS system-memory totals are never substituted for actual GPU allocation. All sampling runs outside the HTTP event loop, is serialized and cached for one second across clients, and external tools have a one-second timeout. Windows counter handles are closed on server shutdown. Polling is driven by foreground clients, so there is no always-running sampling worker.

Install the updated archive and restart ComfyUI to enable the additional telemetry. Standard ComfyUI and older companions continue supplying memory-only readings to the app. No deployment or server restart is performed by building the iOS app.

## Safe transfer publication (companion 1.4.1)

Device-file uploads and URL downloads also work when a destination does not support hard links. The companion falls back to an atomic rename that refuses to replace an existing file (Windows rename, macOS RENAME_EXCL, or Linux RENAME_NOREPLACE). Concurrent duplicate names receive numeric suffixes with either strategy. A small hidden probe checks support before the upload body or download file is streamed. If neither safe method is supported, the transfer fails with an explicit instruction to choose another location; partial files are never exposed under their final names.
