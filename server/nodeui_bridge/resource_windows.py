"""Windows WDDM telemetry through DXGI/PDH. No PowerShell or extra packages."""
from __future__ import annotations

import ctypes as c
import re
import uuid

from .resource_gpu import match_device, memory, number


def aggregate_engines(values, luid):
    engines = {}
    for instance, value in values:
        match = re.search(r"luid_(0x[\da-f]+)_(0x[\da-f]+)_phys_(\d+)_eng_(\d+)", instance.lower())
        if match and (int(match[1], 16), int(match[2], 16)) == luid and number(value) is not None:
            engine = (match[3], match[4])
            engines[engine] = engines.get(engine, 0) + value
    return min(100, max(engines.values())) if engines else None


def adapter_memory(values, luid):
    found = [value for instance, value in values
             if (match := re.search(r"luid_(0x[\da-f]+)_(0x[\da-f]+)_phys_\d+", instance.lower()))
             and (int(match[1], 16), int(match[2], 16)) == luid and number(value) is not None]
    return sum(found) if found else None


class LUID(c.Structure):
    _fields_ = [("low", c.c_uint32), ("high", c.c_int32)]


class AdapterDescription(c.Structure):
    _fields_ = [("name", c.c_wchar * 128), ("vendor", c.c_uint32), ("device", c.c_uint32),
                ("subsystem", c.c_uint32), ("revision", c.c_uint32), ("dedicated", c.c_size_t),
                ("system", c.c_size_t), ("shared", c.c_size_t), ("luid", LUID), ("flags", c.c_uint32)]


class CounterUnion(c.Union):
    _fields_ = [("double", c.c_double), ("large", c.c_int64), ("long", c.c_int32), ("text", c.c_void_p)]


class CounterValue(c.Structure):
    _fields_ = [("status", c.c_uint32), ("value", CounterUnion)]


class CounterItem(c.Structure):
    _fields_ = [("name", c.c_wchar_p), ("value", CounterValue)]


def com_method(pointer, slot, result, *arguments):
    vtable = c.cast(pointer, c.POINTER(c.POINTER(c.c_void_p))).contents
    return c.WINFUNCTYPE(result, c.c_void_p, *arguments)(vtable[slot])


def adapters():
    dxgi = c.WinDLL("dxgi")
    create = dxgi.CreateDXGIFactory1
    create.argtypes = [c.c_void_p, c.POINTER(c.c_void_p)]
    create.restype = c.c_int32
    iid = c.create_string_buffer(uuid.UUID("770aae78-f26f-4dba-a829-253c83d1b387").bytes_le)
    factory = c.c_void_p()
    if create(iid, c.byref(factory)) != 0:
        return []
    result = []
    try:
        enum = com_method(factory, 12, c.c_int32, c.c_uint32, c.POINTER(c.c_void_p))
        for index in range(64):
            adapter = c.c_void_p()
            if enum(factory, index, c.byref(adapter)) != 0:
                break
            try:
                desc = AdapterDescription()
                get = com_method(adapter, 10, c.c_int32, c.POINTER(AdapterDescription))
                if get(adapter, c.byref(desc)) == 0 and not desc.flags & 2:
                    luid = (desc.luid.high & 0xffffffff, desc.luid.low)
                    result.append({"id": f"luid-{luid[0]:08x}-{luid[1]:08x}", "luid": luid,
                                   "name": desc.name, "total": desc.dedicated})
            finally:
                com_method(adapter, 2, c.c_uint32)(adapter)
    finally:
        com_method(factory, 2, c.c_uint32)(factory)
    return result


class WindowsGPUReader:
    def __init__(self):
        self.query = c.c_void_p()
        self.pdh = c.WinDLL("pdh")
        signatures = {
            "PdhOpenQueryW": ([c.c_wchar_p, c.c_size_t, c.POINTER(c.c_void_p)], c.c_int32),
            "PdhAddEnglishCounterW": ([c.c_void_p, c.c_wchar_p, c.c_size_t, c.POINTER(c.c_void_p)], c.c_int32),
            "PdhCollectQueryData": ([c.c_void_p], c.c_int32),
            "PdhGetFormattedCounterArrayW": ([c.c_void_p, c.c_uint32, c.POINTER(c.c_uint32), c.POINTER(c.c_uint32), c.c_void_p], c.c_int32),
            "PdhCloseQuery": ([c.c_void_p], c.c_int32),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.pdh, name)
            function.argtypes, function.restype = args, result
        if self.pdh.PdhOpenQueryW(None, 0, c.byref(self.query)) != 0:
            raise OSError("GPU performance counters unavailable")
        self.engines = self.add(r"\GPU Engine(*)\Utilization Percentage")
        self.dedicated = self.add(r"\GPU Adapter Memory(*)\Dedicated Usage")
        self.primed = False

    def add(self, path):
        handle = c.c_void_p()
        if self.pdh.PdhAddEnglishCounterW(self.query, path, 0, c.byref(handle)) != 0:
            return None
        return handle

    def values(self, handle):
        if handle is None:
            return []
        size, count = c.c_uint32(), c.c_uint32()
        get = self.pdh.PdhGetFormattedCounterArrayW
        # PDH_MORE_DATA is expected on the sizing call; bound allocation defensively.
        get(handle, 0x200 | 0x8000, c.byref(size), c.byref(count), None)
        if not 0 < size.value <= 16 * 1024 * 1024:
            return []
        buffer = c.create_string_buffer(size.value)
        if get(handle, 0x200 | 0x8000, c.byref(size), c.byref(count), buffer) != 0:
            return []
        items = c.cast(buffer, c.POINTER(CounterItem))
        return [(items[i].name, items[i].value.value.double) for i in range(count.value)
                if items[i].value.status in (0, 1)]

    def read(self, primary):
        adapter = match_device(adapters(), primary)
        if not adapter:
            return None
        if self.pdh.PdhCollectQueryData(self.query) != 0:
            return None
        usage = aggregate_engines(self.values(self.engines), adapter["luid"]) if self.primed else None
        self.primed = True
        return {"id": adapter["id"], "name": adapter["name"], "utilizationPercent": usage,
                "memoryKind": "dedicated", "memory": memory(adapter_memory(self.values(self.dedicated), adapter["luid"]), adapter["total"])}

    def close(self):
        if self.query:
            self.pdh.PdhCloseQuery(self.query)
            self.query = c.c_void_p()
