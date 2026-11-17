# Install the optional companion

The companion is a small ComfyUI custom-node extension that enables full folder listings, thumbnails, uploads, server-side URL downloads, and reuse of output files. It runs on ComfyUI's existing port and does not start a separate server. Standard ComfyUI APIs work without it, with a more limited file browser.

## Downloads and access

Open [the latest helper release](https://github.com/Guhl-Design-Studio/nodeui/releases/latest). This repository and its release downloads are public.

Download the named `nodeui_bridge.zip` asset, plus `install-windows.ps1` or `install-macos.sh` if you want an installer. Keep the ZIP and installer together. Use the named companion ZIP rather than GitHub's automatic source-code archive. Review scripts before running them; manual installation is also supported.

Use the latest companion, currently **2.1.2**. It includes shared workflows with ordered images and prompts, per-image Upload/Select/Remove controls, live progress for jobs started by another client, and the existing file-transfer and resource-monitoring tools.

## Manual installation — Windows or macOS

1. Download and extract `nodeui_bridge.zip`.
2. Copy the extracted `nodeui_bridge` folder into `YOUR-COMFYUI-FOLDER/custom_nodes/`. Choose the ComfyUI backend folder containing `main.py`. For ComfyUI Desktop, use the backend directory rather than the application bundle.
3. If a companion is already installed, preserve a backup outside `custom_nodes` so ComfyUI cannot load both copies.
4. Wait until the generation queue is idle, then restart ComfyUI once using its normal launcher.
5. Reload the ComfyUI browser editor to load the updated Shared Input controls, then reconnect NodeUI and refresh **File Browser → Locations**.

Companion 2.0.0 renames the package and API to NodeUI. Version 2.0.1 also accepts `/comfymobile/v1` API requests, so existing mobile builds continue working. The ZIP contains only the 12 runtime files, including `web/shared_input.js`. When updating from 1.x, move the old companion outside `custom_nodes`; the installers do this automatically and preserve a backup.

## Windows installer

Open PowerShell in the folder containing the installer and ZIP, then pass your ComfyUI backend path:

```powershell
.\install-windows.ps1 -ComfyUIPath 'C:\path\to\ComfyUI'
```

If script policy prevents execution, use manual installation instead.

## macOS installer

Open Terminal in the folder containing the installer and ZIP:

```sh
bash install-macos.sh '/path/to/ComfyUI'
```

Both installers preserve an existing companion under `<ComfyUI>/.nodeui-backups/` with a timestamp. They do not download packages, stop ComfyUI, or restart it. Restart manually once the queue is idle.

## Verify installation

On the ComfyUI computer, open `http://localhost:8188/nodeui/v1/capabilities` in a browser, or run:

```powershell
Invoke-RestMethod 'http://localhost:8188/nodeui/v1/capabilities'
```

```sh
curl 'http://localhost:8188/nodeui/v1/capabilities'
```

Use your configured port if it differs from 8188. From another device, replace `localhost` with the ComfyUI computer's reachable address. A working installation reports `apiVersion: 1`, its companion version, and available `roots`. Version 2.1.2 reports `sharedWorkflows: true`, `sharedWorkflowImageOutputs: true`, `promptWorkflows: true`, `downloads: true`, `fileUploads: true`, `fileDeletion: true`, and `resourceMonitoring: true`. It also advertises `executionObservation: true` when the server transport supports forwarding progress and previews.

## Run a workflow from an iPhone or iPad

1. Install the [latest companion 2.1.2 and matching installer](https://github.com/Guhl-Design-Studio/nodeui/releases/latest) in your self-hosted ComfyUI installation and restart ComfyUI. In NodeUI, connect to that server and allow notifications when prompted.
2. Open the [model-free example](../server/examples/shared-image.json) in the ComfyUI web editor or NodeUI and **save it to the server**. For your own workflow, add one enabled **Shared Input** and one enabled **Return Image to NodeUI** on the main canvas. Wire the image or prompt through your processing nodes to the return node. To drive a text widget in the web editor, expose it as an input and connect the prompt output. Groups between them are supported. The example returns the image you send.
3. From Photos or Files, share one or more images and choose **NodeUI** in the apps row (look under **More** if needed). Choose the server and workflow, edit the prompt, and tap **Run**. Numbered previews show the image order supplied by the sharing app. Shared text fills the prompt when available. Otherwise the node supplies its saved default.
4. In Shortcuts, add **Run NodeUI Workflow With Prompt And Images**, choose a workflow, connect one or more images to **Images**, and optionally pass text. The action returns the accepted ComfyUI job ID immediately. Use **Ask Each Time** for a prompt you want to enter on each run.
5. To use the results in your shortcut, add **Receive NodeUI Workflow Output** and connect **Job ID** to the previous action’s result. It returns all output images and videos as files. Follow it with **Quick Look**, **Save to Photo Album**, **Save File**, or another action that accepts files. See [receiver setup and waiting behavior](control-center.md#use-workflow-output-in-the-shortcut).

NodeUI asks for notification permission when you open the app, including before connecting a server or adding custom nodes. If you previously declined, enable notifications in iOS Settings → Notifications → NodeUI.

Expand the result notification for **Copy Image** and **Save to Photos**, or tap it to open the image. With notifications disabled, open **Execution history → Shared workflows** on that server. The phone receives the first image in a batch. ComfyUI saves the whole batch. The phone needs a connection to that server to download the result. iOS controls background delivery timing. Reopen NodeUI after force-quitting it or reconnecting to your server.

The installable folder is `nodeui_bridge`. The installer backs up an existing installation in `<ComfyUI>/.nodeui-backups/`. Keep existing workflows and media in place when updating.

### Multiple image inputs in Share and Shortcuts

Connect **image 1** on Shared Input to an image input in Your workflow. A spare **image 2** connector appears; connecting it adds **image 3**, and so on. This works in ComfyUI and the iOS editor. The **prompt** connector appears at the top, above the image outputs, and keeps its original wiring.

Pass an ordered image list to **Images** in **Run NodeUI Workflow With Prompt And Images**. The first image goes to **image 1**, the second to **image 2**, and so on. Each keeps its own dimensions; they are separate images, rather than a resized batch. Duplicate selections keep their positions. The action preserves the list order supplied by the preceding Shortcuts action, so configure that action to return the order you want.

Existing single-image shortcuts keep their original action and continue to work. To enable multiple images in an older shortcut, replace its **Run NodeUI Workflow With Prompt And Images** action with the new action showing **Images**, then choose the workflow and reconnect its input and Job ID variables.

Each connected image output has its own labeled preview box. The spare unconnected output has none. A slot without a supplied image shows a placeholder. Reopening a new run’s workflow snapshot retains the images supplied to that run, so each preview and a subsequent rerun use the corresponding image. In ComfyUI, use the **Upload** button inside each box to set that numbered image, or **Remove** to clear it. Removing an image preserves later assignments and leaves the uploaded file on the server. In iOS, tap Shared Input to open its details and use each connected image’s **Upload** or **Remove** button; the canvas shows previews only. These assignments survive workflow save/reload. The node fits its connected preview boxes and can be resized back to that compact height.

You can supply fewer images than the highest numbered connected image output. Unfilled connections and the processing branches that require them are omitted for that run, including inside groups. For example, an unused image 2 also skips its scale nodes before reaching an optional image input. Optional downstream inputs use their normal defaults; a required output that still needs the absent branch produces an error before queuing. Supplying the image includes that branch again. Extra images and empty selections produce errors. Spare unconnected outputs do not increase capacity; removing a wire never renumbers later outputs. Submitted images and omitted connections affect only the run, preserving the saved workflow and open draft. This branch handling requires the updated native app and companion.

Install the newly packaged companion and restart ComfyUI, then reload its browser editor and refresh NodeUI’s server connection. The capabilities response must include **`sharedWorkflowImageOutputs: true`**; an earlier 2.1.0 installation without that flag needs the updated archive. The bundled browser extension is specific to Shared Input. Current iOS development builds also accept multiple images from the Photos/Files share sheet, using the same numbered Shared Input slots.

For text-to-image generation without an input image or opening NodeUI, use **Prompt Input** and the **Run NodeUI Workflow With Prompt** action with a Control Center shortcut. See [the prompt popup setup](control-center.md).

## Update, restore, or remove

To update, download the latest ZIP and matching installer, repeat installation, restart ComfyUI when idle, and refresh Locations.

To restore a backup, stop ComfyUI, move the current `custom_nodes/nodeui_bridge` outside `custom_nodes`, and move the saved `.nodeui-backups/nodeui_bridge-...` folder back to `custom_nodes/nodeui_bridge`. Restart once.

To remove the companion, stop ComfyUI and move `custom_nodes/nodeui_bridge` outside `custom_nodes`, then restart. Removing this extension does not modify workflows, models, or media.

## Companion troubleshooting

- **GitHub returns 404:** use the current public repository linked above and its latest release. If a download was moved, return to the release page and select the named asset again.
- **Folders, uploads, or downloads are missing:** install or update the companion, restart ComfyUI when idle, and refresh Locations. An older companion may lack newer transfer capabilities. Without the companion, only files indexed by standard ComfyUI APIs are available.
- **A provider download is restricted:** Hugging Face or Civitai may require an account, permission, or acceptance of a model license. Add an appropriate key under **Settings → Download keys**. Keys are stored in the device Keychain and sent to the selected server when needed. Only connect to servers you trust.
- **A transfer stops:** server-owned URL downloads continue after the client closes but stop when ComfyUI restarts. Device uploads require the client to remain open and connected. Server restarts clear the in-memory download history.

See the [technical guide](technical-help.md) for connection troubleshooting and [API reference](../server/README.md) for transfer behavior and endpoints.
