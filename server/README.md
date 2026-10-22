# NodeUI companion

See [installation instructions](../docs/companion.md) and [release downloads](https://github.com/aguhl0614/nodeui/releases/latest). Copy `comfymobile_bridge` into your ComfyUI `custom_nodes` directory and restart ComfyUI once. No separate process, credentials, port, or frontend extension is installed. It registers routes on the same ComfyUI HTTP server.

Windows portable example: `C:\path\to\ComfyUI\custom_nodes\comfymobile_bridge`.

macOS example: `<ComfyUI>/custom_nodes/comfymobile_bridge`.

Verify with `http://<server>:8188/comfymobile/v1/capabilities`. The response reports API version 1, enabled image thumbnails, upload size, and logical folder roots. Pillow is normally present in ComfyUI; when absent, image requests return the original image instead of a thumbnail.

The app still loads, edits and executes workflows without this companion. Its fallback browser uses ComfyUI's workflow/model endpoints and indexed assets; complete filesystem browsing and server-side reuse of outputs require the companion.

## API version 1

All file paths are relative to a root reported by capabilities. Root paths are never accepted from the client. Traversal, absolute POSIX/Windows paths and symlinks leaving a configured root are rejected.

| Method | Route | Parameters / body |
| --- | --- | --- |
| GET | `/comfymobile/v1/capabilities` | Returns `apiVersion`, `roots`, `thumbnails`, `maxUploadBytes` |
| GET | `/comfymobile/v1/files` | `root`, `path`, `offset=0`, `limit=100`, optional `search`; returns `entries`, `total`, `nextOffset` |
| GET | `/comfymobile/v1/content` | `root`, `path`; streams content, supports HTTP Range through aiohttp |
| GET | `/comfymobile/v1/thumbnail` | `root`, `path`, optional `width=384` (64–1024); image thumbnails |
| POST | `/comfymobile/v1/upload` | `root`, optional `path` query; one multipart file; inputs/workflows only, no overwrite |
| POST | `/comfymobile/v1/copy` | JSON `{"root":"output","path":"folder/image.png"}`; copies into `input/ComfyMobile`, returns ComfyUI-compatible `name`, `subfolder`, `type` |

The legacy multipart upload route accepts Inputs and Workflows only. Model and output folders use the explicit destination API described below for device uploads and URL downloads. Existing input uploads receive a numeric suffix rather than overwriting. Workflow saving uses ComfyUI's existing userdata endpoint and the app's conflict check. The companion respects ComfyUI's request-user workflow folder.

Companion 1.0.1 presents one model root per category, such as `model:checkpoints`, merging its existing configured locations and nested folders. Repeated physical locations and duplicate relative filenames appear once; the first configured location supplies a duplicate file, matching ComfyUI's search order. Missing model locations are omitted. Older indexed root IDs remain usable until an open browser refreshes its Locations list.

## Tests

Run `python3 -m unittest discover -s server/tests -v` from the repository root. Filesystem tests need only Python's standard library. Route integration tests additionally use aiohttp and Pillow, already included with a usual ComfyUI install.

## URL downloads (companion 1.1.0)

In NodeUI, open **Settings → Download keys** to save optional Hugging Face and Civitai keys in the device Keychain. Public files need no key. Keys are shared across server profiles on that device and sent to the selected server only when resolving or downloading a matching provider URL. The companion keeps credentials in memory, scopes authorization to the provider host, and strips it when following cross-host redirects. Keys, source URLs and signed storage URLs are excluded from job responses and error messages.

Browse to the destination folder, then choose **File actions → Download from URL**. Paste a direct HTTP/HTTPS file URL, a Hugging Face repository/tree/blob/resolve URL, or a Civitai model page (including `modelVersionId`). Repository pages show folders and paginated files; Civitai pages show the available versions/files. Select one file, optionally enter a filename, and start the download. Restricted files still require a valid key, account access, and any provider license acceptance. Generic webpage scraping and interactive website sign-in are unsupported.

Downloads run on the server, with two concurrent transfers and a queue. They continue when the app is closed, and appear under **File actions → Downloads** after reconnection. Progress includes downloaded bytes and total size when known. Failed/cancelled jobs can be retried with the device's current key. Jobs and retry information remain in memory for up to 24 hours after completion; restarting ComfyUI interrupts running jobs and clears the history. Downloads do not resume across server restarts.

Each root now has a separate `downloadDestinations` array containing server-issued location IDs and display paths. In merged model categories the app lets you choose a physical location, defaulting to the first one containing the browsed subfolder, or the first configured location otherwise. Missing destination subfolders are created. The legacy multipart permissions and merged browsing/search order remain unchanged; model roots still report `writable: false` for that route. Companion 1.2.0 adds a separate device-file upload route using these explicit destinations. Custom-node/configuration locations remain excluded. Display paths are returned for destination selection, but filesystem paths are never accepted from clients.

Files stream to a hidden temporary file on the destination filesystem. Completed files are atomically published without replacing existing files; duplicate names receive numeric suffixes. Downloads have no 100 MB upload limit. Failed/cancelled transfers remove their temporary files. After an abrupt server/process termination, a hidden `.comfymobile-download-*` temporary file may remain and can be removed while the server is stopped.

| Method | Route | Parameters / body |
| --- | --- | --- |
| GET | `/comfymobile/v1/capabilities` | Adds `downloads: true`, `version: "1.1.0"`, and root `downloadDestinations` |
| GET | `/comfymobile/v1/downloads/locations` | `root`, optional `path`; returns `destinations`, `defaultLocation` |
| POST | `/comfymobile/v1/downloads/resolve` | JSON `url`, optional `key`, `folder`, `cursor`; returns `files`, `folder`, `nextCursor`. Omit `folder` for the URL's initial folder; use an empty string for repository root. |
| POST | `/comfymobile/v1/downloads` | JSON `url`, `root`, optional `path`, `location`, `filename`, `key`; returns job, HTTP 202 |
| GET | `/comfymobile/v1/downloads` | Lists this ComfyUI user's jobs |
| GET | `/comfymobile/v1/downloads/{id}` | Returns one owned job |
| POST | `/comfymobile/v1/downloads/{id}/cancel` | Cancels an owned job |
| POST | `/comfymobile/v1/downloads/{id}/retry` | JSON optional `key`; retries a failed/cancelled job, returns a new job |

Job fields: `id`, `root`, `path`, `name`, `state` (`queued`, `downloading`, `completed`, `failed`, `cancelled`), `receivedBytes`, nullable `totalBytes`, nullable `error`, nullable `provider`, and `updated`. `path` is the destination folder during transfer and the completed relative filename after success. Jobs are scoped using ComfyUI's request-user workflow directory. Older companions omit the added capabilities; the app directs users to update rather than attempting an incompatible fallback.




## Device file uploads (companion 1.2.0)

Browse to a model, output or temporary folder and choose **File actions → Upload file**. Confirm the destination location when a model category spans multiple directories, then choose a file using the native Files picker. Uploads start immediately, show the filename and a cancel action, and refresh the browsed folder on completion. Keep NodeUI open until the upload finishes. Inputs retain their existing upload/import flow; Workflows retains JSON import.

Capabilities now advertise `fileUploads: true` and `version: "1.2.0"`. The new `POST /comfymobile/v1/upload-file` endpoint accepts the raw file body and query parameters `root`, `path`, `location`, and `filename`. Location IDs come from `/downloads/locations`, including the preferred physical location for the selected subfolder. Unknown locations, path traversal and outward symlinks are rejected. Only configured roots can receive files; the request must resolve to a ComfyUI user. Existing files receive numeric suffixes instead of being replaced.

The server streams uploaded chunks into a hidden temporary file on the destination filesystem. This endpoint has no 100 MB multipart limit. A complete file is published atomically without replacing another file; interrupted or cancelled transfers remove the temporary file. A server/process crash may leave `.comfymobile-upload-*` files, which can be removed while ComfyUI is stopped. Uploads run only while the app remains connected; they are separate from the server-owned Downloads queue.
