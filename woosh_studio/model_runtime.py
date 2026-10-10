"""One cancellable heavy-model lease, persistent workers, bounded residency."""
from __future__ import annotations

import hashlib
import json
import os
import queue
import subprocess
import sys
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from threading import Event, RLock, Thread
from uuid import uuid4

from .jobs import JobControl
from .runtime import apply_offline_environment


def model_revision(path: Path) -> str:
    """Installed file identity: replacement, repair, and directory changes invalidate it."""
    path = path.resolve()
    records = []
    if path.is_dir():
        for file in sorted(path.rglob("*")):
            if file.is_file() and file.suffix in {".safetensors", ".pt", ".th", ".bin", ".json", ".yaml", ".spm", ".model"}:
                info = file.stat()
                records.append((file.relative_to(path).as_posix(), info.st_size, info.st_mtime_ns))
    return hashlib.sha256(json.dumps([str(path), records]).encode()).hexdigest()


class PersistentWorker:
    def __init__(self, module: str, environment: dict[str, str]):
        self.process = subprocess.Popen(
            [sys.executable, "-m", module], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", env=environment,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        self.messages: queue.Queue[str | None] = queue.Queue()
        self.errors: deque[str] = deque(maxlen=16)
        self.threads = [Thread(target=self._stdout, daemon=True), Thread(target=self._stderr, daemon=True)]
        for thread in self.threads:
            thread.start()

    def _stdout(self):
        try:
            for line in self.process.stdout:
                self.messages.put(line)
        finally:
            self.messages.put(None)

    def _stderr(self):
        for line in self.process.stderr:
            self.errors.append(line.strip())

    def request(self, payload: dict, control: JobControl, progress, timeout: float = 3600) -> dict:
        request_id = uuid4().hex
        control.checkpoint()
        if self.process.poll() is not None:
            raise RuntimeError("模型工作进程已退出")
        self.process.stdin.write(json.dumps({**payload, "request_id": request_id}, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        deadline = time.monotonic() + timeout
        while True:
            control.checkpoint()
            if time.monotonic() > deadline:
                raise RuntimeError("模型工作进程超时，请重试该任务")
            try:
                raw = self.messages.get(timeout=0.1)
            except queue.Empty:
                if self.process.poll() is not None:
                    raise RuntimeError("模型工作进程退出：" + " · ".join(self.errors))
                continue
            if raw is None:
                raise RuntimeError("模型工作进程连接中断：" + " · ".join(self.errors))
            try:
                event = json.loads(raw)
            except ValueError:
                self.errors.append(raw.strip())
                continue
            if event.get("request_id") != request_id:
                continue
            if event.get("event") in {"progress", "loaded"}:
                progress(event)
            elif event.get("event") == "result":
                return event.get("result", {})
            elif event.get("event") == "error":
                raise RuntimeError(event.get("message", "模型工作进程失败"))

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        for thread in self.threads:
            thread.join(timeout=2)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()


class ModelRuntimeManager:
    def __init__(self, models_root, settings=None):
        self._models_root = models_root
        self._settings = settings
        self.lock = RLock()
        self._depth = 0
        self._active_key = None
        self._unload = None
        self._worker: PersistentWorker | None = None
        self._closed = Event()
        self._last_used = time.monotonic()
        self._state = {"state": "unloaded", "model_id": None, "load_count": 0,
                       "cache_hits": 0, "load_seconds": 0.0, "generation_seconds": 0.0, "pid": None}
        self._janitor = Thread(target=self._expire, daemon=True)
        self._janitor.start()

    @contextmanager
    def sequence(self, control: JobControl):
        while not self.lock.acquire(timeout=0.1):
            control.checkpoint()
            if self._closed.is_set():
                raise RuntimeError("模型服务已关闭")
        self._depth += 1
        try:
            control.checkpoint()
            if self._closed.is_set():
                raise RuntimeError("模型服务已关闭")
            yield
        finally:
            self._last_used = time.monotonic()
            self._depth -= 1
            if self._depth == 0 and self._settings and self._settings().model_residency == "release":
                self._drop()
            self.lock.release()

    def _drop(self):
        if self._worker is not None:
            self._worker.close()
            self._worker = None
        if self._unload is not None:
            self._unload()
            self._unload = None
        self._active_key = None
        self._state.update(state="unloaded", model_id=None, pid=None)

    @contextmanager
    def lease(self, key, model_id, control, unload=None):
        with self.sequence(control):
            if key != self._active_key:
                self._drop()
                self._active_key = key
                self._unload = unload
                self._state.update(state="loading", model_id=model_id)
            else:
                self._state["cache_hits"] += 1
            try:
                yield
                self._state["state"] = "ready"
            except BaseException:
                self._drop()
                self._state["state"] = "failed"
                raise
            finally:
                self._last_used = time.monotonic()

    def run(self, module: str, payload: dict, control: JobControl, progress) -> dict:
        model_path = Path(payload.get("model_path", "."))
        operation = payload.get("operation", payload["command"])
        identity = payload.get("model_revision") or model_revision(model_path)
        key = (module, operation, identity, payload.get("device", "cpu"), payload.get("memory_mode", "default"))
        with self.lease(key, payload.get("model_id", model_path.name), control):
            fresh = self._worker is None
            if fresh:
                environment = os.environ.copy()
                apply_offline_environment(environment)
                root = self._models_root() if callable(self._models_root) else self._models_root
                environment.update(PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
                                   HF_HOME=str(Path(root) / ".huggingface"), TORCH_HOME=str(Path(root) / ".torch"),
                                   WOOSH_STUDIO_OFFLINE="1")
                self._worker = PersistentWorker(module, environment)
                self._worker.request({"command": "ping"}, control, lambda event: None, timeout=30)
                self._state["pid"] = self._worker.process.pid
            started = time.monotonic()
            def event_received(event):
                if event.get("event") == "loaded":
                    self._state["load_count"] += 1
                    self._state["load_seconds"] = float(event.get("seconds", 0))
                    self._state["state"] = "ready"
                else:
                    self._state["state"] = "loading" if event.get("progress", 1) < 0.1 else "running"
                    progress(event)
            if fresh and payload["command"] != "load":
                self._worker.request({**payload, "command":"load", "operation":operation, "model_revision":identity}, control, event_received, timeout=600)
            started = time.monotonic()
            result = self._worker.request({**payload, "model_revision": identity}, control, event_received, timeout=600 if payload["command"] == "load" else 3600)
            self._state["generation_seconds"] = 0.0 if payload["command"] == "load" else time.monotonic() - started
            return result

    def mark_running(self):
        self._state["state"] = "running"

    def mark_loaded(self, seconds: float):
        self._state["load_count"] += 1
        self._state["load_seconds"] = seconds
        self._state["state"] = "ready"

    def status(self) -> dict:
        return {**self._state, "idle_seconds": max(0, time.monotonic() - self._last_used)}

    def release(self):
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("模型正在使用，请等待任务结束或先取消任务")
        try:
            self._drop()
        finally:
            self.lock.release()

    @contextmanager
    def maintenance(self):
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("模型正在使用，请等待任务结束或先取消任务")
        try:
            self._drop()
            yield
        finally:
            self.lock.release()

    def _expire(self):
        while not self._closed.wait(2):
            settings = self._settings() if self._settings else None
            ttl = settings.model_idle_seconds if settings else 600
            if settings and settings.model_residency == "keep":
                continue
            if time.monotonic() - self._last_used >= ttl and self.lock.acquire(blocking=False):
                try:
                    if time.monotonic() - self._last_used >= ttl:
                        self._drop()
                finally:
                    self.lock.release()

    def close(self):
        self._closed.set()
        # JobManager cancels and joins active jobs before this call.
        with self.lock:
            self._drop()
        self._janitor.join(timeout=3)
