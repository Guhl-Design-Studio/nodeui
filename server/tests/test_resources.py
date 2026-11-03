"""Telemetry fixtures cover each provider without requiring GPU drivers."""
from pathlib import Path
import plistlib
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nodeui_bridge import resource_gpu as gpu
from nodeui_bridge.resource_windows import WindowsGPUReader, aggregate_engines, adapter_memory
from nodeui_bridge.resources import ResourceCollector, primary_device


class ResourceTests(unittest.TestCase):
    def test_nvidia_uuid_matches_remapped_primary_not_physical_index(self):
        data = b'GPU-aaaa, 00000000:01:00.0, NVIDIA Example, 4, 100, 24000, 0\nGPU-bbbb, 00000000:04:00.0, NVIDIA Example, 88, 12000, 24000, 1\n'
        rows = gpu.parse_nvidia(data)
        selected = gpu.match_device(rows, {"uuid": "bbbb", "name": "NVIDIA Example"})
        self.assertEqual(selected["utilizationPercent"], 88)
        self.assertEqual(selected["memory"]["usedBytes"], 12000 * 1048576)
        self.assertIsNone(gpu.match_device(rows, {"name": "NVIDIA Example"}))
        self.assertIsNone(gpu.match_device(rows[:1], {"uuid": "bbbb", "name": "NVIDIA Example"}))

    def test_unsupported_nvidia_values_are_unknown(self):
        reading = gpu.parse_nvidia(b'GPU-a, 0000:01:00.0, Example, [N/A], [N/A], 24000, 0\n')[0]
        self.assertIsNone(reading["utilizationPercent"])
        self.assertIsNone(reading["memory"]["usedBytes"])

    def test_amd_sysfs_uses_pci_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            device = root / "0000:04:00.0"
            device.mkdir()
            for name, value in {"vendor": "0x1002", "gpu_busy_percent": "79", "mem_info_vram_used": "1024", "mem_info_vram_total": "4096"}.items():
                (device / name).write_text(value)
            card = root / "card1"
            card.mkdir()
            (card / "device").symlink_to(device)
            reading = gpu.amd_linux({"pci": "00000000:04:00.0"}, root)
            self.assertEqual(reading["utilizationPercent"], 79)
            self.assertEqual(reading["memory"], {"usedBytes": 1024, "totalBytes": 4096})
            self.assertIsNone(gpu.amd_linux({"pci": "0000:09:00.0"}, root))
            (device / "gpu_busy_percent").unlink()
            self.assertIsNone(gpu.amd_linux({"pci": "0000:04:00.0"}, root)["utilizationPercent"])

    def test_apple_unified_memory_is_gpu_allocation_not_system_usage(self):
        data = plistlib.dumps([{"IOClass": "AGXAcceleratorG13X", "IORegistryEntryID": 42,
                               "PerformanceStatistics": {"Device Utilization %": 51, "In use system memory": 2048,
                                                         "Alloc system memory": 8192}}])
        reading = gpu.parse_macos(data, {"type": "mps"}, 16384)
        self.assertEqual(reading["memoryKind"], "shared")
        self.assertEqual(reading["memory"]["usedBytes"], 2048)
        self.assertEqual(reading["memory"]["totalBytes"], 16384)
        self.assertEqual(reading["utilizationPercent"], 51)

    def test_macos_amd_matches_adapter_and_keeps_missing_metrics_unknown(self):
        data = plistlib.dumps([{"IOClass": "AMDRadeon", "model": b"AMD Example\0", "IORegistryEntryID": 7,
                               "PerformanceStatistics": {"Device Utilization %": 32, "vramUsedBytes": 2048}}])
        reading = gpu.parse_macos(data, {"type": "mps", "name": "AMD Example", "memory": {"totalBytes": 8192}}, 16384)
        self.assertEqual(reading["memoryKind"], "dedicated")
        self.assertEqual(reading["memory"]["totalBytes"], 8192)
        self.assertEqual(reading["utilizationPercent"], 32)
        self.assertIsNone(gpu.parse_macos(data, {"type": "mps", "name": "Other GPU"}, 16384))

    def test_windows_busiest_engine_sums_processes_without_summing_engines(self):
        readings = [("pid_1_luid_0x00000000_0x000000ff_phys_0_eng_0_engtype_Compute", 40),
                    ("pid_2_luid_0x00000000_0x000000ff_phys_0_eng_0_engtype_Compute", 30),
                    ("pid_1_luid_0x00000000_0x000000ff_phys_0_eng_1_engtype_Copy", 50),
                    ("pid_9_luid_0x00000000_0x000000ee_phys_0_eng_0_engtype_Compute", 100)]
        self.assertEqual(aggregate_engines(readings, (0, 255)), 70)
        self.assertIsNone(aggregate_engines(readings, (0, 123)))
        self.assertEqual(adapter_memory([("luid_0x00000000_0x000000ff_phys_0", 8192)], (0, 255)), 8192)

    def test_invalid_measurements_are_not_zero(self):
        for value in [None, -1, float("nan"), float("inf"), "N/A", 101]:
            self.assertIsNone(gpu.percent(value))
        self.assertEqual(gpu.percent(0), 0)
        self.assertIsNone(gpu.memory(1, 0)["usedBytes"])
        self.assertIsNone(gpu.memory(99, 10)["usedBytes"])

    def test_windows_provider_primes_rates_and_keeps_memory_available(self):
        reader = WindowsGPUReader.__new__(WindowsGPUReader)
        reader.query = 1
        reader.pdh = types.SimpleNamespace(PdhCollectQueryData=lambda _: 0)
        reader.engines, reader.dedicated, reader.primed = "engines", "memory", False
        reader.values = lambda counter: [("pid_1_luid_0x00000000_0x000000ff_phys_0_eng_0", 80)] if counter == "engines" else [("luid_0x00000000_0x000000ff_phys_0", 4096)]
        with patch("nodeui_bridge.resource_windows.adapters", return_value=[{"id": "luid-ff", "name": "AMD Example", "luid": (0, 255), "total": 8192}]):
            first = reader.read({"name": "AMD Example"})
            second = reader.read({"name": "AMD Example"})
            self.assertIsNone(reader.read({"name": "Other GPU"}))
        self.assertIsNone(first["utilizationPercent"])
        self.assertEqual(first["memory"]["usedBytes"], 4096)
        self.assertEqual(second["utilizationPercent"], 80)

    def test_cpu_uses_deltas_and_ram_uses_available_memory(self):
        psutil = types.SimpleNamespace(cpu_times=Mock(side_effect=[
            types.SimpleNamespace(_asdict=lambda: {"user": 10, "idle": 10}),
            types.SimpleNamespace(_asdict=lambda: {"user": 15, "idle": 25})]),
            virtual_memory=lambda: types.SimpleNamespace(total=64, available=48))
        collector = ResourceCollector()
        with patch.dict(sys.modules, {"psutil": psutil}):
            cpu, ram = collector.cpu_ram()
            self.assertIsNone(cpu)
            cpu, ram = collector.cpu_ram()
        self.assertEqual(cpu, 25)
        self.assertEqual(ram["usedBytes"], 16)

    def test_one_second_cache_and_independent_gpu_failure(self):
        collector = ResourceCollector()
        primary = {"id": "gpu0", "name": "Example", "memoryKind": "dedicated", "memory": gpu.memory(2, 8)}
        with patch.object(collector, "cpu_ram", return_value=(30, gpu.memory(10, 32))) as cpu, \
             patch("nodeui_bridge.resources.primary_device", return_value=primary), \
             patch.object(collector.gpu, "read", side_effect=OSError("Driver missing")), \
             patch("nodeui_bridge.resources.time.monotonic", side_effect=[5, 5.5]):
            first = collector.sample()
            second = collector.sample()
        self.assertIs(first, second)
        self.assertEqual(cpu.call_count, 1)
        self.assertEqual(first["cpuPercent"], 30)
        self.assertIsNone(first["gpu"]["utilizationPercent"])
        self.assertEqual(first["gpu"]["memory"]["usedBytes"], 2)

    def test_cpu_re_primes_after_a_long_gap_without_foreground_clients(self):
        collector = ResourceCollector()
        psutil = types.SimpleNamespace(cpu_times=lambda: types.SimpleNamespace(_asdict=lambda: {"user": 20, "idle": 40}),
                                       virtual_memory=lambda: types.SimpleNamespace(total=64, available=48))
        collector.previous_cpu = (20, 10, 5)
        with patch.dict(sys.modules, {"psutil": psutil}), patch("nodeui_bridge.resources.time.monotonic", return_value=100):
            cpu, ram = collector.cpu_ram()
        self.assertIsNone(cpu, "Do not show a minutes-long average as a live CPU reading")
        self.assertEqual(ram["usedBytes"], 16)

    def test_provider_external_command_is_bounded_without_shell(self):
        with patch("nodeui_bridge.resource_gpu.subprocess.run", return_value=types.SimpleNamespace(stdout=b"")) as run:
            gpu.nvidia({"uuid": "not-found"})
        self.assertEqual(run.call_args.kwargs["timeout"], 1)
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_selected_device_is_passed_to_worker_and_changes_invalidate_cache(self):
        collector = ResourceCollector()
        with patch.object(collector, "cpu_ram", return_value=(30, gpu.memory(10, 32))), \
             patch("nodeui_bridge.resources.primary_device", return_value=None) as primary, \
             patch("nodeui_bridge.resources.time.monotonic", return_value=5):
            collector.sample("cuda:1")
            primary.assert_called_with("cuda:1")
            collector.sample("cuda:0")
            primary.assert_called_with("cuda:0")
        self.assertEqual(primary.call_count, 2)

    def test_primary_metadata_preserves_selected_cuda_or_hip_device(self):
        selected = types.SimpleNamespace(type="cuda", index=1)
        for hip in (None, "6.4"):
            with self.subTest(hip=hip):
                properties = types.SimpleNamespace(name="Example GPU", uuid="GPU-bbbb")
                properties_for = Mock(return_value=properties)
                management = types.ModuleType("comfy.model_management")
                management.get_torch_device = Mock(side_effect=AssertionError("Must use the device captured on the event-loop thread"))
                management.get_torch_device_name = lambda device: "cuda:1 Example GPU"
                management.get_total_memory = lambda device: 8192
                management.get_free_memory = lambda device: 6144
                management.torch = types.SimpleNamespace(version=types.SimpleNamespace(hip=hip),
                                                         cuda=types.SimpleNamespace(get_device_properties=properties_for))
                comfy = types.ModuleType("comfy")
                comfy.model_management = management
                with patch.dict(sys.modules, {"comfy": comfy, "comfy.model_management": management}), \
                     patch("nodeui_bridge.resources.hip_pci", return_value="0000:04:00.0"):
                    result = primary_device(selected)
                properties_for.assert_called_once_with(selected)
                self.assertEqual(result["uuid"], "GPU-bbbb")
                self.assertEqual(result["memory"]["usedBytes"], 2048)
                self.assertEqual(result["vendor"], "amd" if hip else "nvidia")
                if hip:
                    self.assertEqual(result["pci"], "0000:04:00.0")


if __name__ == "__main__":
    unittest.main()
