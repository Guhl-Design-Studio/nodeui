# Install the optional companion

The companion is a small ComfyUI custom-node extension that enables full folder listings, thumbnails, uploads, server-side URL downloads, and reuse of output files. It runs on ComfyUI's existing port and does not start a separate server. Standard ComfyUI APIs work without it, with a more limited file browser.

## Downloads and access

Open [the latest helper release](https://github.com/aguhl0614/nodeui/releases/latest) while signed in to a GitHub account with repository access. This repository and its releases are private; a 404 may mean your account lacks access.

Download the named `comfymobile_bridge.zip` asset, plus `install-windows.ps1` or `install-macos.sh` if you want an installer. Keep the ZIP and installer together. Use the named companion ZIP rather than GitHub's automatic source-code archive. Review scripts before running them; manual installation is also supported.

Use companion **1.2.0 or later** for device file uploads. Version 1.1.0 added server-side URL downloads; 1.2.0 includes both capabilities.

## Manual installation — Windows or macOS

1. Download and extract `comfymobile_bridge.zip`.
2. Copy the extracted `comfymobile_bridge` folder into `YOUR-COMFYUI-FOLDER/custom_nodes/`. Choose the ComfyUI backend folder containing `main.py`. For ComfyUI Desktop, use the backend directory rather than the application bundle.
3. If a companion is already installed, preserve a backup outside `custom_nodes` so ComfyUI cannot load both copies.
4. Wait until the generation queue is idle, then restart ComfyUI once using its normal launcher.
5. Reconnect and refresh **File Browser → Locations**.

The internal folder name `comfymobile_bridge` is retained for compatibility. The ZIP contains only four companion runtime files.

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

Both installers preserve an existing companion under `<ComfyUI>/.comfymobile-backups/` with a timestamp. They do not download packages, stop ComfyUI, or restart it. Restart manually once the queue is idle.

## Verify installation

On the ComfyUI computer, open `http://localhost:8188/comfymobile/v1/capabilities` in a browser, or run:

```powershell
Invoke-RestMethod 'http://localhost:8188/comfymobile/v1/capabilities'
```

```sh
curl 'http://localhost:8188/comfymobile/v1/capabilities'
```

Use your configured port if it differs from 8188. From another device, replace `localhost` with the ComfyUI computer's reachable address. A working installation reports `apiVersion: 1`, its companion version, and available `roots`. Version 1.2.0 also reports `downloads: true` and `fileUploads: true`.

## Update, restore, or remove

To update, download the latest ZIP and matching installer, repeat installation, restart ComfyUI when idle, and refresh Locations.

To restore a backup, stop ComfyUI, move the current `custom_nodes/comfymobile_bridge` outside `custom_nodes`, and move the saved `.comfymobile-backups/comfymobile_bridge-...` folder back to `custom_nodes/comfymobile_bridge`. Restart once.

To remove the companion, stop ComfyUI and move `custom_nodes/comfymobile_bridge` outside `custom_nodes`, then restart. Removing this extension does not modify workflows, models, or media.

## Companion troubleshooting

- **GitHub returns 404:** sign in to an account with access to this private repository. Website downloads now point to GitHub and require the same access.
- **Folders, uploads, or downloads are missing:** install or update the companion, restart ComfyUI when idle, and refresh Locations. An older companion may lack newer transfer capabilities. Without the companion, only files indexed by standard ComfyUI APIs are available.
- **A provider download is restricted:** Hugging Face or Civitai may require an account, permission, or acceptance of a model license. Add an appropriate key under **Settings → Download keys**. Keys are stored in the device Keychain and sent to the selected server when needed. Only connect to servers you trust.
- **A transfer stops:** server-owned URL downloads continue after the client closes but stop when ComfyUI restarts. Device uploads require the client to remain open and connected. Server restarts clear the in-memory download history.

See the [technical guide](technical-help.md) for connection troubleshooting and [API reference](../server/README.md) for transfer behavior and endpoints.
