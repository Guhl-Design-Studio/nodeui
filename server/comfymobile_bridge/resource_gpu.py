"""Read-only GPU providers. Missing drivers/counters return unknown, never zero."""
from __future__ import annotations

import csv
import ctypes
import ctypes.util
import math
from pathlib import Path
import plistlib
import re
import subprocess
import sys


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (ValueError, TypeError):
        return None


def percent(value):
    value = number(value)
    return value if value is not None and value <= 100 else None


def memory(used=None, total=None):
    used, total = number(used), number(total)
    total = total if total else None
    used = used if total is not None and used is not None and used <= total else None
    return {"usedBytes": used, "totalBytes": total}


def command(arguments):
    # No shell, privilege escalation, or commands supplied by an HTTP caller.
    return subprocess.run(arguments, capture_output=True, timeout=1, check=True,
                          creationflags=0x08000000 if sys.platform == "win32" else 0).stdout


def canonical_uuid(value):
    return str(value or "").lower().removeprefix("gpu-").replace("-", "")


def canonical_pci(value):
    match = re.fullmatch(r"(?:([\da-f]+):)?([\da-f]{2}):([\da-f]{2})\.([\da-f])", str(value or "").lower())
    if not match:
        return None
    return tuple(int(part or "0", 16) for part in match.groups())


def match_device(devices, primary):
    """Never infer a physical adapter from the remapped CUDA/HIP logical index."""
    compared_identity = False
    for key, normalize in (("uuid", canonical_uuid), ("pci", canonical_pci), ("luid", str)):
        identity = normalize(primary.get(key)) if primary.get(key) else None
        if identity:
            compared_identity |= any(d.get(key) for d in devices)
            matches = [d for d in devices if d.get(key) and normalize(d[key]) == identity]
            if len(matches) == 1:
                return matches[0]
    if compared_identity:
        return None
    # A unique full adapter name is usable; identical multi-GPU names remain unknown.
    name = primary.get("name", "").strip().casefold()
    matches = [d for d in devices if d.get("name", "").strip().casefold() == name]
    return matches[0] if name and len(matches) == 1 else None


def parse_nvidia(data):
    devices = []
    for fields in csv.reader(data.decode().splitlines(), skipinitialspace=True):
        if len(fields) != 7:
            continue
        uuid, pci, name, usage, used, total, _index = fields
        used, total = number(used), number(total)
        devices.append({"id": uuid, "uuid": uuid, "pci": pci, "name": name,
                        "utilizationPercent": percent(usage), "memoryKind": "dedicated",
                        "memory": memory(None if used is None else used * 1048576,
                                         None if total is None else total * 1048576)})
    return devices


def nvidia(primary):
    data = command(["nvidia-smi", "--query-gpu=uuid,pci.bus_id,name,utilization.gpu,memory.used,memory.total,index",
                    "--format=csv,noheader,nounits"])
    return match_device(parse_nvidia(data), primary)


def amd_linux(primary, root=Path("/sys/class/drm")):
    devices = []
    for card in sorted(root.glob("card[0-9]*")):
        if not re.fullmatch(r"card\d+", card.name):
            continue
        device = card / "device"
        try:
            if (device / "vendor").read_text().strip().lower() != "0x1002":
                continue
            pci = device.resolve().name
            def read(name):
                try:
                    return number((device / name).read_text().strip())
                except OSError:
                    return None
            devices.append({"id": pci, "pci": pci, "utilizationPercent": percent(read("gpu_busy_percent")),
                            "memoryKind": "dedicated", "memory": memory(read("mem_info_vram_used"), read("mem_info_vram_total"))})
        except OSError:
            continue
    return match_device(devices, primary)


def parse_macos(data, primary, ram_total):
    accelerators = []
    def visit(entry):
        stats = entry.get("PerformanceStatistics")
        if isinstance(stats, dict):
            apple = str(entry.get("IOClass", "")).startswith("AGX")
            name = entry.get("model", "")
            if isinstance(name, bytes):
                name = name.rstrip(b"\0").decode(errors="replace")
            used = stats.get("In use system memory") if apple else stats.get("vramUsedBytes")
            total = ram_total if apple else stats.get("vramTotalBytes", primary.get("memory", {}).get("totalBytes"))
            accelerators.append({"id": str(entry.get("IORegistryEntryID", entry.get("IOClass", ""))),
                                 "name": name, "apple": apple,
                                 "utilizationPercent": percent(stats.get("Device Utilization %")),
                                 "memoryKind": "shared" if apple else "dedicated", "memory": memory(used, total)})
        for child in entry.get("IORegistryEntryChildren", []):
            visit(child)
    for entry in plistlib.loads(data):
        visit(entry)
    if primary.get("type") == "mps":
        apple = [d for d in accelerators if d["apple"]]
        if len(apple) == 1:
            return apple[0]
        if not apple and len(accelerators) == 1 and primary.get("name", "mps") == "mps":
            return accelerators[0]
    return match_device(accelerators, primary)


def hip_pci(index):
    """Ask HIP for the physical PCI identity after its visibility remapping."""
    library = ctypes.util.find_library("amdhip64")
    if not library:
        torch = sys.modules.get("torch")
        if torch and getattr(torch, "__file__", None):
            bundled = Path(torch.__file__).parent / "lib" / ("amdhip64.dll" if sys.platform == "win32" else "libamdhip64.so")
            if bundled.is_file():
                library = str(bundled)
    if not library:
        return None
    hip = ctypes.CDLL(library)
    get_pci = hip.hipDeviceGetPCIBusId
    get_pci.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
    get_pci.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(64)
    return buffer.value.decode() if get_pci(buffer, len(buffer), index) == 0 else None


class GPUReader:
    def __init__(self):
        self.windows = None

    def read(self, primary, ram_total):
        if not primary:
            return None
        try:
            if sys.platform == "darwin":
                return parse_macos(command(["/usr/sbin/ioreg", "-a", "-r", "-c", "IOAccelerator"]), primary, ram_total)
            if primary.get("vendor") == "nvidia":
                return nvidia(primary)
            if sys.platform.startswith("linux") and primary.get("vendor") == "amd":
                return amd_linux(primary)
            if sys.platform == "win32":
                from .resource_windows import WindowsGPUReader
                if self.windows is None:
                    self.windows = WindowsGPUReader()
                return self.windows.read(primary)
        except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError):
            pass
        return None

    def close(self):
        if self.windows:
            self.windows.close()
            self.windows = None
