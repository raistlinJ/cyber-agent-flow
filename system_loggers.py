"""Auxiliary runtime loggers for network capture and system calls."""

import os
import re
import shutil
import subprocess
import threading
import time
from typing import Callable, Optional

from timestamp_utils import now_filename_timestamp, now_timestamp


def _sanitize_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(name or "unknown"))[:80]


def _list_up_interfaces() -> set[str]:
    """Return interface names that currently report UP via `ip link`."""
    if not shutil.which("ip"):
        return set()

    try:
        result = subprocess.run(
            ["ip", "-o", "link", "show"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:
        return set()

    if result.returncode != 0:
        return set()

    interfaces = set()
    for line in result.stdout.splitlines():
        # Example: 2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> ...
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        iface = parts[1].strip().split("@", 1)[0]
        flags_blob = parts[2]
        if "<" not in flags_blob or ">" not in flags_blob:
            continue
        flags = flags_blob.split("<", 1)[1].split(">", 1)[0].split(",")
        if "UP" in flags:
            interfaces.add(iface)
    return interfaces


class NetworkCaptureLogger:
    """Continuously run per-interface packet capture for all UP interfaces."""

    def __init__(self, base_dir: str = None, event_callback: Callable = None, poll_interval: int = 3):
        self._event_callback = event_callback
        self._poll_interval = max(1, int(poll_interval))
        self._base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
        self._run_id = None
        self._capture_dir = None
        self._running = False
        self._monitor_thread = None
        self._lock = threading.Lock()
        self._captures = {}

    def _emit(self, event_type: str, payload: dict):
        if not self._event_callback:
            return
        try:
            self._event_callback({"type": event_type, **payload})
        except Exception:
            pass

    def _start_capture_locked(self, iface: str):
        if iface in self._captures or not self._capture_dir:
            return
        if not shutil.which("tcpdump"):
            raise RuntimeError("tcpdump not found on PATH")

        file_name = f"{_sanitize_name(iface)}_{now_filename_timestamp()}.pcap"
        file_path = os.path.join(self._capture_dir, file_name)

        cmd = ["tcpdump", "-i", iface, "-U", "-n", "-w", file_path]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._captures[iface] = {"proc": proc, "path": file_path}
        self._emit("network_capture_started", {"interface": iface, "file": file_name})

    def _stop_capture_locked(self, iface: str, reason: str = "stopped"):
        info = self._captures.pop(iface, None)
        if not info:
            return

        proc = info.get("proc")
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        self._emit(
            "network_capture_stopped",
            {
                "interface": iface,
                "file": os.path.basename(info.get("path", "")),
                "reason": reason,
            },
        )

    def _monitor_loop(self):
        while self._running:
            up_ifaces = _list_up_interfaces()
            with self._lock:
                existing_ifaces = set(self._captures.keys())

                for iface in list(existing_ifaces):
                    proc = self._captures.get(iface, {}).get("proc")
                    if proc and proc.poll() is not None:
                        self._stop_capture_locked(iface, reason="process_exited")

                for iface in sorted(up_ifaces):
                    if iface not in self._captures:
                        try:
                            self._start_capture_locked(iface)
                        except Exception as exc:
                            self._emit(
                                "network_capture_error",
                                {"interface": iface, "error": str(exc)},
                            )

                for iface in list(self._captures.keys()):
                    if iface not in up_ifaces:
                        self._stop_capture_locked(iface, reason="interface_down")

            time.sleep(self._poll_interval)

    def start(self, run_id: str):
        if self._running:
            return

        if not run_id:
            raise ValueError("run_id is required")

        self._run_id = run_id
        self._capture_dir = os.path.join(self._base_dir, "runs", run_id, "network_capture")
        os.makedirs(self._capture_dir, exist_ok=True)

        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        self._emit("network_capture_logger_started", {"run_id": run_id})

    def stop(self):
        if not self._running:
            return

        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=3)
            self._monitor_thread = None

        with self._lock:
            for iface in list(self._captures.keys()):
                self._stop_capture_locked(iface, reason="logger_stopped")

        self._emit("network_capture_logger_stopped", {"run_id": self._run_id})

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def active_interfaces(self) -> list[str]:
        with self._lock:
            return sorted(self._captures.keys())


class SyscallLogger:
    """Capture system calls using strace and persist them with unified timestamps."""

    def __init__(self, base_dir: str = None, event_callback: Callable = None):
        self._base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
        self._event_callback = event_callback
        self._run_id = None
        self._proc: Optional[subprocess.Popen] = None
        self._reader_thread = None
        self._log_path = None
        self._lock = threading.Lock()

    def _emit(self, event_type: str, payload: dict):
        if not self._event_callback:
            return
        try:
            self._event_callback({"type": event_type, **payload})
        except Exception:
            pass

    def _reader_loop(self):
        if not self._proc or not self._proc.stderr or not self._log_path:
            return

        with open(self._log_path, "a") as f:
            f.write(f"{now_timestamp()} [syscall-logger] started\n")
            for line in self._proc.stderr:
                f.write(f"{now_timestamp()} {line.rstrip()}\n")
            f.write(f"{now_timestamp()} [syscall-logger] stopped\n")

    def start(self, run_id: str, target_pid: int = None):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                return

            if not shutil.which("strace"):
                raise RuntimeError("strace not found on PATH")

            pid = int(target_pid or os.getpid())
            self._run_id = run_id

            syscalls_dir = os.path.join(self._base_dir, "runs", run_id, "syscalls")
            os.makedirs(syscalls_dir, exist_ok=True)
            self._log_path = os.path.join(syscalls_dir, f"syscalls_{now_filename_timestamp()}.log")

            cmd = ["strace", "-f", "-s", "256", "-p", str(pid)]
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

            self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self._reader_thread.start()
            self._emit("syscall_logger_started", {"run_id": run_id, "target_pid": pid})

    def stop(self):
        with self._lock:
            proc = self._proc
            thread = self._reader_thread
            self._proc = None
            self._reader_thread = None

        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        if thread:
            thread.join(timeout=3)

        self._emit("syscall_logger_stopped", {"run_id": self._run_id})

    @property
    def is_running(self) -> bool:
        with self._lock:
            return bool(self._proc and self._proc.poll() is None)
