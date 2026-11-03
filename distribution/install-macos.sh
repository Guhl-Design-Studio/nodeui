#!/bin/bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 /path/to/ComfyUI" >&2
    exit 2
fi
comfy_root="$(cd -- "$1" && pwd -P)"
if [[ ! -f "$comfy_root/main.py" ]]; then
    echo "Choose the ComfyUI folder containing main.py." >&2
    exit 1
fi
distribution_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
archive="$distribution_dir/nodeui_bridge.zip"
if [[ ! -f "$archive" ]]; then
    echo "Keep nodeui_bridge.zip beside this installer." >&2
    exit 1
fi
custom_nodes="$comfy_root/custom_nodes"
destination="$custom_nodes/nodeui_bridge"
staging="$destination.installing-$$"
temporary="$(mktemp -d -t nodeui-install)"
backup=""
legacy_backup=""
legacy="$custom_nodes/comfymobile_bridge"
installed=false
staging_owned=false
cleanup() {
    if [[ "$installed" == false && -n "$backup" && -d "$backup" && ! -e "$destination" ]]; then
        mv -- "$backup" "$destination"
    fi
    if [[ "$installed" == false && -n "$legacy_backup" && -d "$legacy_backup" && ! -e "$legacy" ]]; then
        mv -- "$legacy_backup" "$legacy"
    fi
    if [[ "$staging_owned" == true && -e "$staging" ]]; then rm -rf -- "$staging"; fi
    rm -rf -- "$temporary"
}
trap cleanup EXIT
/usr/bin/unzip -q "$archive" -d "$temporary"
for runtime_file in __init__.py filesystem.py routes.py downloads.py resources.py resource_gpu.py resource_windows.py; do
    if [[ ! -f "$temporary/nodeui_bridge/$runtime_file" ]]; then
        echo "The archive is missing runtime file $runtime_file." >&2
        exit 1
    fi
done
mkdir -p -- "$custom_nodes"
if [[ -e "$staging" ]]; then
    echo "Remove the incomplete staging folder before retrying: $staging" >&2
    exit 1
fi
staging_owned=true
cp -R -- "$temporary/nodeui_bridge" "$staging"
if [[ -e "$destination" ]]; then
    mkdir -p -- "$comfy_root/.nodeui-backups"
    backup="$comfy_root/.nodeui-backups/nodeui_bridge-$(date +%Y%m%d-%H%M%S)-$$"
    if [[ -e "$backup" ]]; then
        echo "Backup already exists: $backup" >&2
        exit 1
    fi
    mv -- "$destination" "$backup"
fi
if [[ -e "$legacy" ]]; then
    mkdir -p -- "$comfy_root/.nodeui-backups"
    legacy_backup="$comfy_root/.nodeui-backups/legacy-bridge-$(date +%Y%m%d-%H%M%S)-$$"
    [[ ! -e "$legacy_backup" ]] || { echo "Backup already exists: $legacy_backup" >&2; exit 1; }
    mv -- "$legacy" "$legacy_backup"
fi
mv -- "$staging" "$destination"
installed=true
echo "Installed: $destination"
[[ -z "$backup" ]] || echo "Previous version preserved: $backup"
echo "Wait until the ComfyUI queue is idle, then restart ComfyUI once."
echo "Verify: curl http://localhost:8188/nodeui/v1/capabilities"
