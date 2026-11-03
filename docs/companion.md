# Install the optional companion

The companion is a small ComfyUI custom-node extension that enables full folder listings, thumbnails, uploads, server-side URL downloads, and reuse of output files. It runs on ComfyUI's existing port and does not start a separate server. Standard ComfyUI APIs work without it, with a more limited file browser.

## Downloads and access

Open [the latest helper release](https://github.com/Guhl-Design-Studio/nodeui/releases/latest). This repository and its release downloads are public.

Download the named `nodeui_bridge.zip` asset, plus `install-windows.ps1` or `install-macos.sh` if you want an installer. Keep the ZIP and installer together. Use the named companion ZIP rather than GitHub's automatic source-code archive. Review scripts before running them; manual installation is also supported.

Use the latest companion, currently **2.0.0**. It includes device uploads, URL downloads, file deletion, server resource monitoring, and safe publication of completed transfers.

## Manual installation — Windows or macOS

1. Download and extract `nodeui_bridge.zip`.
2. Copy the extracted `nodeui_bridge` folder into `YOUR-COMFYUI-FOLDER/custom_nodes/`. Choose the ComfyUI backend folder containing `main.py`. For ComfyUI Desktop, use the backend directory rather than the application bundle.
3. If a companion is already installed, preserve a backup outside `custom_nodes` so ComfyUI cannot load both copies.
4. Wait until the generation queue is idle, then restart ComfyUI once using its normal launcher.
5. Reconnect and refresh **File Browser → Locations**.

Companion 2.0.0 renames the package and API to NodeUI. Update the NodeUI app together with the companion. The ZIP contains only the seven runtime files. When updating from 1.x, move the old companion outside `custom_nodes`; the installers do this automatically and preserve a backup.

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

Use your configured port if it differs from 8188. From another device, replace `localhost` with the ComfyUI computer's reachable address. A working installation reports `apiVersion: 1`, its companion version, and available `roots`. Version 2.0.0 reports `downloads: true`, `fileUploads: true`, `fileDeletion: true`, and `resourceMonitoring: true`.

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
