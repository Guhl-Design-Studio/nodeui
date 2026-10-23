"""Shared, bounded telemetry sampling. CPU/RAM describe the whole server."""
from __future__ import annotations

import threading
import time
import platform
import uuid

from .resource_gpu import GPUReader, hip_pci, memory, percent


def current_device():
    """Capture the event-loop thread's selected device before entering a worker."""
    try:
        import comfy.model_management as management
        return management.get_torch_device()
    except Exception:
        return None


def primary_device(device=None):
    import comfy.model_management as management
    if device is None:
        device = management.get_torch_device()
    kind = device.type
    if kind == "cpu":
        return None
    result = {"type": kind, "name": management.get_torch_device_name(device), "id": str(device),
              "memoryKind": "shared" if kind == "mps" and platform.machine() == "arm64" else "dedicated", "memory": memory()}
    if kind != "mps":
        try:
            total = management.get_total_memory(device)
            free = management.get_free_memory(device)
            result["memory"] = memory(total - free, total)
        except Exception:
            pass
    if kind == "cuda":
        torch = management.torch
        props = torch.cuda.get_device_properties(device)
        device_uuid = getattr(props, "uuid", None)
        if isinstance(device_uuid, (bytes, bytearray)) and len(device_uuid) == 16:
            device_uuid = uuid.UUID(bytes=bytes(device_uuid))
        result.update(name=props.name, uuid=str(device_uuid or ""), pci=getattr(props, "pci_bus_id", None),
                      vendor="amd" if getattr(torch.version, "hip", None) else "nvidia")
        if result["vendor"] == "amd" and not result["pci"]:
            try:
                result["pci"] = hip_pci(device.index if device.index is not None else torch.cuda.current_device())
            except (OSError, AttributeError, ValueError):
                pass
    elif kind == "privateuseone":
        # torch-directml exposes a name, but adapter numbering need not match DXGI.
        try:
            import torch_directml
            result["name"] = torch_directml.device_name(device.index or 0)
        except (ImportError, AttributeError, RuntimeError):
            pass
    return result


class ResourceCollector:
    def __init__(self):
        self.lock = threading.Lock()
        self.cached = None
        self.cached_at = 0
        self.cached_device = None
        self.previous_cpu = None
        self.gpu = GPUReader()

    def cpu_ram(self):
        try:
            import psutil
            times = psutil.cpu_times()._asdict()
            total = sum(v for k, v in times.items() if k not in ("guest", "guest_nice"))
            idle = times.get("idle", 0) + times.get("iowait", 0)
            previous = self.previous_cpu
            sampled_at = time.monotonic()
            self.previous_cpu = (total, idle, sampled_at)
            cpu = None
            if previous and total > previous[0] and 0 <= sampled_at - previous[2] <= 10:
                cpu = percent(100 * (1 - (idle - previous[1]) / (total - previous[0])))
            ram = psutil.virtual_memory()
            return cpu, memory(ram.total - ram.available, ram.total)
        except (ImportError, OSError, AttributeError):
            return None, memory()

    def sample(self, device=None):
        with self.lock:
            if self.cached is not None and self.cached_device == str(device) and time.monotonic() - self.cached_at < 1:
                return self.cached
            cpu, ram = self.cpu_ram()
            try:
                primary = primary_device(device)
            except Exception:
                primary = None
            gpu = None
            if primary:
                gpu = {key: primary.get(key) for key in ("id", "name", "memoryKind", "memory")}
                gpu["utilizationPercent"] = None
                try:
                    reading = self.gpu.read(primary, ram["totalBytes"])
                    if reading:
                        gpu.update({key: reading[key] for key in ("id", "utilizationPercent", "memoryKind")})
                        if reading["memory"]["usedBytes"] is not None:
                            gpu["memory"] = reading["memory"]
                except Exception:
                    # A driver may fail independently of CPU/RAM or ComfyUI's own memory reader.
                    pass
            result = {"sampledAt": time.time(), "cpuPercent": cpu, "ram": ram, "gpu": gpu}
            self.cached, self.cached_at = result, time.monotonic()
            self.cached_device = str(device)
            return result

    def close(self):
        with self.lock:
            self.gpu.close()


collector = ResourceCollector()
