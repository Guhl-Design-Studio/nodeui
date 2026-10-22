# Connection setup and technical help

This guide copies the website's technical guidance for convenient use alongside the server helpers. [Companion installation and transfer troubleshooting](companion.md) are maintained here on GitHub. Repository access is required while the repository is private.

## Connect your computer

1. Start ComfyUI on your computer and confirm that its normal web interface works. Install the models and custom nodes required by your workflow there.
2. Put the computer and your device on the same trusted network for a local connection. Configure ComfyUI to listen on your network interface and allow only the necessary firewall access. Consult the [ComfyUI installation instructions](https://docs.comfy.org/installation/comfyui_portable_windows) for your installation.
3. In the client walkthrough, enter a recognizable server name and its reachable address, including the port when needed: `http://YOUR-COMPUTER-ADDRESS:8188`.
4. Allow Local Network access when iOS asks, then connect. Add or reconnect servers under **Settings → Servers**.
5. Open Workflows and choose a saved workflow, import JSON, or start a new graph.

For access away from home, use a trusted VPN or properly protected HTTPS endpoint. Plain HTTP does not encrypt workflow contents or credentials in transit. Do not expose an unprotected ComfyUI server directly to the internet.

Choose **Set up later** in the walkthrough to explore offline. Generation and server files require a connected computer; generation runs on that computer.

## Everyday controls

- **Pan:** drag the graph. **Zoom:** pinch.
- **Edit a node:** tap it to open its inspector.
- **Move or resize:** touch and hold a node, choose the action, then confirm or cancel the preview.
- **Connect:** tap compatible ports, or touch and hold a port and choose Connect port.
- **Save:** use workflow actions to Save or Save As. Export JSON for a separate copy.
- **Appearance:** open Settings for appearance, highlight color, OLED black, and alternate icons.

## Troubleshooting

### Cannot connect

Check that ComfyUI is running, the address and port are correct, and the device can reach the computer. On iOS, check **Settings → Privacy & Security → Local Network**. Check VPN, Wi-Fi isolation, firewall, and HTTPS certificate settings. A device's `localhost` refers to itself, not the ComfyUI computer.

### Folders or transfers are missing

Follow [companion installation and troubleshooting](companion.md#companion-troubleshooting). Install or update, restart ComfyUI when idle, then refresh Locations.

### A workflow does not run

Check the same workflow in desktop ComfyUI. Install its required models and custom nodes there. Arbitrary JavaScript frontend extensions cannot execute in the native client. Node groups, including nested groups, can be edited and run directly. Premium templates may require third-party credits.

### A provider download is restricted

Some Hugging Face or Civitai files require your provider account, permission, or acceptance of the model's license. Add an appropriate key under **Settings → Download keys**. Only connect to trusted servers. See [companion troubleshooting](companion.md#companion-troubleshooting).

### Remove data or keys

Use Remove beside a key under **Settings → Download keys** before uninstalling; Keychain items can survive app deletion. Deleting the app removes its local app-container data, subject to device backups. Remove server files separately on the server. Files exported to Photos or Files remain until you delete them. See the website's [privacy choices](https://nodeui.guhlstudio.com/privacy/#choices).
