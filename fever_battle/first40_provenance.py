"""Source/build snapshots and explicitly scoped cost sampling for research."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import time
import zipfile

from .model import ROOT


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_files():
    files = set()
    for directory in ("core", "ai", "fever", "fever_battle", "bench_fever", "tools", "test"):
        files.update(p for p in (ROOT / directory).rglob("*") if p.is_file()
                     and p.suffix in (".cpp", ".h", ".cc", ".py"))
    files.update((ROOT / "data/fever").glob("*.json"))
    files.update(ROOT / name for name in ("config.json", "build.ps1", "AGENTS.md"))
    return sorted(files)


def fingerprints():
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in source_files()}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def host_info():
    cpu = platform.processor()
    if os.name == "nt":
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                           r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            cpu = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    return dict(platform=platform.platform(), cpu=cpu, logical_cpus=os.cpu_count(),
                python=platform.python_version())


def snapshot(output, binaries, build_manifest=None):
    files = source_files()
    hashes = fingerprints()
    with zipfile.ZipFile(output / "source-snapshot.zip", "x", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
    (output / "tracked.patch").write_bytes(subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=ROOT))
    manifest = dict(schema="ama.first40.manifest.v1", timestamp_unix=time.time(),
        head=git("rev-parse", "HEAD"), branch=git("branch", "--show-current"),
        status=git("status", "--porcelain=v1", "--untracked-files=all"),
        source_sha256=hashes, source_snapshot_sha256=sha(output / "source-snapshot.zip"),
        tracked_patch_sha256=sha(output / "tracked.patch"), host=host_info(),
        binaries={str(Path(p).resolve()): sha(p) for p in binaries})
    if build_manifest:
        manifest["build_manifest"] = json.loads(Path(build_manifest).read_text(encoding="utf-8-sig"))
        manifest["build_manifest_sha256"] = sha(build_manifest)
        built = manifest["build_manifest"]
        for path, value in built.get("binaries", {}).items():
            if sha(path) != value:
                raise ValueError("build binary fingerprint mismatch")
        for path, value in built.get("source_sha256", {}).items():
            if sha(ROOT / path) != value:
                raise ValueError("build source fingerprint mismatch")
    return manifest


def process_sample(processes):
    """CPU includes this Python driver plus both native processes, not host load.

    Windows supplies lifetime peak RSS. Linux provides CPU and VmHWM from proc.
    Unsupported/closed handles return null rather than fabricated zeros.
    """
    result = {"python_driver": dict(cpu_seconds=time.process_time(), peak_bytes=None)}
    for name, process in processes.items():
        cpu, peak = None, None
        if os.name == "nt":
            from ctypes import wintypes
            handle = wintypes.HANDLE(int(process._handle))
            values = [wintypes.FILETIME() for _ in range(4)]
            api = ctypes.WinDLL("kernel32", use_last_error=True).GetProcessTimes
            api.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
            api.restype = wintypes.BOOL
            if api(handle, *(ctypes.byref(v) for v in values)):
                cpu = sum((v.dwHighDateTime << 32) + v.dwLowDateTime for v in values[2:]) / 1e7
            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                    (key, ctypes.c_size_t) for key in ("PeakWorkingSetSize", "WorkingSetSize",
                        "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                        "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            api = ctypes.WinDLL("psapi").GetProcessMemoryInfo
            api.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
            api.restype = wintypes.BOOL
            if api(handle, ctypes.byref(counters), counters.cb):
                peak = counters.PeakWorkingSetSize
        elif platform.system() == "Linux":
            try:
                stat = Path(f"/proc/{process.pid}/stat").read_text().rsplit(")", 1)[1].split()
                cpu = (int(stat[11]) + int(stat[12])) / os.sysconf("SC_CLK_TCK")
                status = Path(f"/proc/{process.pid}/status").read_text().splitlines()
                peak = next(int(line.split()[1]) * 1024 for line in status if line.startswith("VmHWM:"))
            except (OSError, ValueError, StopIteration):
                pass
        result[name] = dict(cpu_seconds=cpu, peak_bytes=peak)
    return result
