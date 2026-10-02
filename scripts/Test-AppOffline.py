r"""Offline regressions using only local verified Lua and synthetic legal scripts.

Run with .runtime\python\python.exe -I scripts\Test-AppOffline.py
Use --report PATH for JSON evidence. Outputs stay in disposable TEMP fixtures.
"""
import argparse
import ctypes
import json
import linecache
import os
import runpy
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
APP = Path(__file__).resolve().parents[1] / "Lua Obfuscator.pyw"
API = runpy.run_path(str(APP), run_name="offline_audit")
if "--baseline" in sys.argv:
    baseline = subprocess.run(["git", "-C", str(APP.parent), "show", "HEAD:" + APP.name], capture_output=True, check=True, timeout=15)
    API = {"__file__": str(APP), "__name__": "offline_audit_baseline"}
    baseline_filename = str(APP) + " (Git HEAD baseline)"
    linecache.cache[baseline_filename] = (len(baseline.stdout), None, baseline.stdout.decode("utf-8").splitlines(keepends=True), baseline_filename)
    exec(compile(baseline.stdout, baseline_filename, "exec"), API)
APPLICATION = API["QApplication"].instance() or API["QApplication"]([])
MEASUREMENTS = []


def working_set_bytes(pid):
    """Sample only known synthetic-job processes; no process inventory required."""
    if os.name != "nt" or not pid:
        return None
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [(name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return None
    try:
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        return int(counters.WorkingSetSize) if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb) else None
    finally:
        kernel.CloseHandle(handle)


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fleece-lua-offline-")
        self.root = Path(self.temp.name)
        self.window = API["LuaObfuscator"]()
        self.window.stale_cleanup_timer.stop()
        self.assertIsNotNone(self.window.lua_path, "verified local Lua runtime required")
        self.assertIsNotNone(self.window.cli_path, "local pinned engine required")
        self.lua = self.window.lua_path
        self.cli = self.window.cli_path
        self.window.app_dir = self.root
        (self.root / ".runtime").mkdir()
        self.window.refresh_tool_paths = lambda: None

    def tearDown(self):
        self.window.close()
        APPLICATION.processEvents()
        self.temp.cleanup()

    def source(self, text="local t={2,3,5}; local n=0; for _,v in ipairs(t) do n=n+v end; print(n)\n", suffix=".lua"):
        source = self.root / ("synthetic" + suffix)
        source.write_text(text, encoding="utf-8")
        self.window.set_source_file(source)
        self.window.output_folder = self.root / "outputs"
        return source

    def wait_for_job(self, timeout=30):
        start = time.perf_counter()
        while self.window.running and time.perf_counter() - start < timeout:
            APPLICATION.processEvents()
            time.sleep(0.001)
        self.assertFalse(self.window.running, "bounded synthetic job timed out")
        self.assertIsNone(self.window.process)
        self.assertIsNone(self.window.validation_process)
        self.assertIsNone(self.window.work_dir)
        self.assertIsNone(self.window.staged_output)

    def test_running_job_cannot_change_selection(self):
        source = self.source()
        output = self.root / "outputs" / "synthetic.obfuscated.lua"
        self.window.output_file = output
        self.window.running = True
        other = self.root / "other.lua"
        other.write_text("return false", encoding="utf-8")
        self.window.set_source_file(other)
        self.assertEqual(self.window.source_file, source)
        self.assertEqual(self.window.output_file, output)

    def test_cancel_during_final_log_drain_is_honored(self):
        self.window.running = True
        self.window.process = API["QProcess"](self.window)
        self.window.cancel_obfuscation()
        self.assertTrue(self.window.cancel_requested)

    def test_work_root_cannot_redirect_cleanup(self):
        work = self.root / ".runtime" / "work"
        outside = self.root / "outside"
        outside.mkdir()
        victim = outside / "job-old"
        victim.mkdir()
        sentinel = victim / "keep.lua"
        sentinel.write_text("return true", encoding="utf-8")
        old = time.time() - API["WORK_CLEANUP_MIN_AGE_SECONDS"] - 60
        os.utime(victim, (old, old))
        # Windows directory junctions do not require symlink privileges.
        if os.name == "nt":
            completed = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(work), str(outside)], capture_output=True, timeout=10)
            self.assertEqual(completed.returncode, 0)
        else:
            os.symlink(outside, work, target_is_directory=True)
        try:
            self.assertEqual(API["cleanup_stale_work_directories"](work), 0)
            self.assertTrue(sentinel.is_file())
            self.source()
            self.window.start_obfuscation()
            self.assertFalse(self.window.running)
            self.assertTrue(sentinel.is_file())
        finally:
            self.window.close()
            work.rmdir() if os.name == "nt" else work.unlink()

    def test_missing_compiler_fails_closed(self):
        self.source()
        self.window.running = True
        self.window.active_target = "lua"
        self.window.lua_path = self.root / "missing-runtime" / "lua54.exe"
        self.window.output_file = self.root / "outputs" / "synthetic.obfuscated.lua"
        self.window.output_file.parent.mkdir()
        staged = self.root / "synthetic-stage.lua"
        staged.write_text("not valid Lua", encoding="utf-8")
        self.window.staged_output = staged
        self.window.start_output_validation(staged.stat().st_size)
        self.assertEqual(self.window.status_label.text(), "Failed")
        self.assertFalse(self.window.output_file.exists())

    def test_invalid_input_and_atomic_publish_preserve_outputs(self):
        source = self.source("local = broken\n")
        before = source.read_bytes()
        self.window.start_obfuscation()
        self.wait_for_job()
        self.assertEqual(self.window.status_label.text(), "Failed")
        self.assertFalse(self.window.output_file.exists())
        self.assertEqual(source.read_bytes(), before)
        staged = self.root / "staged.lua"
        staged.write_text("return true", encoding="utf-8")
        output = self.root / "existing.lua"
        output.write_bytes(b"existing")
        self.window.output_file = output
        self.window.staged_output = staged
        with patch.object(API["os"], "replace", side_effect=OSError("synthetic full disk")):
            self.assertFalse(self.window.publish_staged_output())
        self.assertEqual(output.read_bytes(), b"existing")
        self.assertEqual(list(self.root.glob(".*.tmp")), [])

    def test_actual_qprocess_cancel_cleans_work(self):
        self.source()
        self.window.start_obfuscation()
        self.assertTrue(self.window.running)
        self.window.cancel_obfuscation()
        self.wait_for_job()
        self.assertEqual(self.window.status_label.text(), "Cancelled")
        self.assertFalse(self.window.output_file.exists())
        self.assertEqual(list((self.root / ".runtime" / "work").iterdir()), [])

    def test_missing_process_and_rejected_output_never_publish(self):
        self.source()
        self.window.lua_path = self.root / "missing.exe"
        self.window.start_obfuscation()
        self.wait_for_job()
        self.assertEqual(self.window.status_label.text(), "Failed")
        self.assertFalse(self.window.output_file.exists())
        self.window.lua_path = self.lua
        self.window.running = True
        self.window.active_target = "lua"
        self.window.output_file = self.root / "existing.lua"
        self.window.output_file.write_bytes(b"existing")
        self.window.staged_output = self.root / "invalid-stage.lua"
        self.window.staged_output.write_text("local = broken", encoding="utf-8")
        self.window.start_output_validation(self.window.staged_output.stat().st_size)
        self.wait_for_job()
        self.assertEqual(self.window.status_label.text(), "Failed")
        self.assertEqual(self.window.output_file.read_bytes(), b"existing")

    def test_overwrite_decline_preserves_existing_output(self):
        self.source()
        output = self.window.output_folder / "synthetic.obfuscated.lua"
        output.parent.mkdir()
        output.write_bytes(b"existing")
        with patch.object(API["QMessageBox"], "question", return_value=API["QMessageBox"].No):
            self.window.start_obfuscation()
        self.assertFalse(self.window.running)
        self.assertEqual(output.read_bytes(), b"existing")
        self.assertEqual(self.window.status_label.text(), "Cancelled")

    def test_obfuscation_and_syntax_validation_do_not_execute_source(self):
        marker = self.root / "must-not-exist.txt"
        text = f"local f=assert(io.open('{marker.as_posix()}', 'w')); f:write('synthetic execution marker'); f:close()\n"
        self.source(text)
        self.window.level_dropdown.select("Medium")
        self.window.start_obfuscation()
        self.wait_for_job()
        self.assertEqual(self.window.status_label.text(), "Done")
        self.assertFalse(marker.exists(), "obfuscation must not execute input scripts")

    def test_verified_engine_presets_semantics_and_event_loop(self):
        from PySide6.QtCore import QTimer
        text = "local t={2,3,5}; local n=0; for _,v in ipairs(t) do n=n+v end; print(n)\n"
        for level in API["PRESET_MAP"]:
            source = self.source(text)
            self.window.output_folder = self.root / ("outputs-" + level)
            self.window.level_dropdown.select(level)
            ticks = []
            memory = []
            child_memory = []
            baseline_rss = working_set_bytes(os.getpid())
            timer = QTimer()
            timer.setInterval(10)
            def sample():
                ticks.append(time.perf_counter())
                rss = working_set_bytes(os.getpid())
                if rss is not None:
                    memory.append(rss)
                child = self.window.process or self.window.validation_process
                child_rss = working_set_bytes(child.processId()) if child is not None else None
                if child_rss is not None:
                    child_memory.append(child_rss)
            timer.timeout.connect(sample)
            start = time.perf_counter()
            timer.start()
            self.window.start_obfuscation()
            self.wait_for_job(timeout=45)
            timer.stop()
            finished = time.perf_counter()
            elapsed = finished - start
            self.assertEqual(self.window.status_label.text(), "Done", self.window.log_box.toPlainText()[-2000:])
            output = self.window.output_file
            result = subprocess.run([str(self.lua), "-E", str(output)], cwd=self.root, stdin=subprocess.DEVNULL, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr[-1000:])
            self.assertEqual(result.stdout.strip(), b"10")
            self.assertEqual(source.read_text(encoding="utf-8"), text)
            gaps = [b - a for a, b in zip([start] + ticks, ticks + [finished])]
            MEASUREMENTS.append({"case": "Lua 5.4 " + level, "seconds": round(elapsed, 4), "source_bytes": source.stat().st_size, "output_bytes": output.stat().st_size, "timer_ticks": len(ticks), "max_event_gap_ms": round(max(gaps) * 1000, 3), "baseline_rss_bytes": baseline_rss, "sampled_peak_rss_bytes": max(memory or [baseline_rss]), "sampled_peak_child_rss_bytes": max(child_memory) if child_memory else None})
            if elapsed >= 0.02:
                self.assertGreater(len(ticks), 0)
            self.assertLess(max(gaps), 2.0)

    def test_luau_typed_input_all_presets(self):
        for level in API["PRESET_MAP"]:
            source = self.source("local message: string = 'synthetic-luau'\nprint(message)\n", ".luau")
            self.window.output_folder = self.root / ("luau-" + level)
            self.window.level_dropdown.select(level)
            start = time.perf_counter()
            self.window.start_obfuscation()
            self.wait_for_job(timeout=45)
            self.assertEqual(self.window.status_label.text(), "Done", self.window.log_box.toPlainText()[-2000:])
            self.assertGreater(self.window.output_file.stat().st_size, 0)
            MEASUREMENTS.append({"case": "Luau " + level, "seconds": round(time.perf_counter() - start, 4), "source_bytes": source.stat().st_size, "output_bytes": self.window.output_file.stat().st_size, "limitation": "no verified Luau runtime installed; generated output not executed"})

    def test_synthetic_lua_language_edges_and_medium_scale(self):
        cases = {
            "closure-varargs": ("local function outer(x) return function(...) local t={...}; return x+#t end end; print(outer(4)(1,2,3))\n", b"7"),
            "bitwise-integer": ("local n=(9//2)+(3<<2); print(n & 15)\n", b"0"),
            "long-strings-unicode": ("--[=[synthetic comment]=]\nlocal s=[=[hello \u03bb]=]; print(s)\n", "hello \u03bb".encode()),
            "coroutine": ("local c=coroutine.create(function() coroutine.yield(5); return 9 end); local _,a=coroutine.resume(c); local _,b=coroutine.resume(c); print(a+b)\n", b"14"),
            "medium-scale": ("local n=0\n" + "n=n+1\n" * 256 + "print(n)\n", b"256"),
        }
        for name, (text, expected) in cases.items():
            with self.subTest(name=name):
                source = self.source(text)
                self.window.output_folder = self.root / name
                self.window.level_dropdown.select("Medium")
                start = time.perf_counter()
                self.window.start_obfuscation()
                self.wait_for_job(timeout=45)
                self.assertEqual(self.window.status_label.text(), "Done", self.window.log_box.toPlainText()[-2000:])
                result = subprocess.run([str(self.lua), "-E", str(self.window.output_file)], cwd=self.root, stdin=subprocess.DEVNULL, capture_output=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr[-1000:])
                self.assertEqual(result.stdout.strip(), expected)
                MEASUREMENTS.append({"case": name, "seconds": round(time.perf_counter() - start, 4), "source_bytes": source.stat().st_size, "output_bytes": self.window.output_file.stat().st_size})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path)
    parser.add_argument("--baseline", action="store_true", help="maintainer-only comparison against local Git HEAD")
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(OfflineTests)
    start = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "seconds": round(time.perf_counter() - start, 4), "measurements": MEASUREMENTS, "failure_details": [text for _, text in result.failures + result.errors]}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
