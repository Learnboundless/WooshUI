from __future__ import annotations

import asyncio
import traceback
from collections.abc import Callable
from threading import Event, RLock
from typing import Any

from .schemas import ErrorCode, JobEvent, JobKind, JobStatus, StudioError, utc_now
from .storage import LibraryDatabase


TERMINAL_STATUSES = {
    JobStatus.COMPLETED,
    JobStatus.PARTIAL,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
    JobStatus.INTERRUPTED,
}


class JobCancelled(Exception):
    pass


class JobControl:
    def __init__(self) -> None:
        self.cancelled = Event()
        self.paused = Event()

    def checkpoint(self) -> None:
        if self.cancelled.is_set():
            raise JobCancelled()
        while self.paused.is_set():
            self.cancelled.wait(0.1)
            if self.cancelled.is_set():
                raise JobCancelled()


JobWorker = Callable[
    [str, Callable[..., None], JobControl],
    dict[str, Any],
]


class JobManager:
    def __init__(self, database: LibraryDatabase):
        self.database = database
        self._jobs: dict[str, JobEvent] = {job.id: job for job in database.recent_jobs()}
        self._controls: dict[str, JobControl] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = RLock()

    def submit(
        self, kind: JobKind, payload: dict[str, Any], worker: JobWorker
    ) -> JobEvent:
        job = JobEvent(kind=kind, payload=payload)
        control = JobControl()
        with self._lock:
            self._jobs[job.id] = job
            self._controls[job.id] = control
            self.database.save_job(job)
            self._tasks[job.id] = asyncio.create_task(
                self._execute(job.id, worker, control)
            )
        return job

    async def _execute(
        self, job_id: str, worker: JobWorker, control: JobControl
    ) -> None:
        self.update(job_id, status=JobStatus.LOADING, stage="准备中", progress=0.01)
        try:
            result = await asyncio.to_thread(
                worker,
                job_id,
                lambda **changes: self.update(job_id, **changes),
                control,
            )
            self.update(
                job_id,
                status=JobStatus.PARTIAL if result.get("partial") else JobStatus.COMPLETED,
                stage="部分完成 · 可重试失败项" if result.get("partial") else "已完成",
                progress=1,
                result=result,
            )
        except JobCancelled:
            self.update(
                job_id,
                status=JobStatus.CANCELLED,
                stage="已取消",
                error=StudioError(
                    code=ErrorCode.JOB_CANCELLED, message="任务已取消"
                ),
            )
        except RuntimeError as error:
            message = str(error)
            code = error_code_for_message(message)
            self.update(
                job_id,
                status=JobStatus.FAILED,
                stage="失败",
                error=StudioError(code=code, message=message, detail=f"失败阶段：{self.get(job_id).stage}\n{traceback.format_exc()[-12000:]}"),
            )
        except Exception as error:  # pragma: no cover - defensive boundary
            self.update(
                job_id,
                status=JobStatus.FAILED,
                stage="失败",
                error=StudioError(
                    code=ErrorCode.INVALID_REQUEST,
                    message=str(error),
                    detail=f"失败阶段：{self.get(job_id).stage}\n{traceback.format_exc()[-12000:]}",
                ),
            )

    async def shutdown(self):
        for control in self._controls.values():
            control.cancelled.set()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    def update(self, job_id: str, **changes: Any) -> JobEvent:
        with self._lock:
            current = self._jobs[job_id]
            changes["updated_at"] = utc_now()
            updated = current.model_copy(update=changes)
            self._jobs[job_id] = updated
            self.database.save_job(updated)
            return updated

    def get(self, job_id: str) -> JobEvent:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            return self._jobs[job_id]

    def list(self) -> list[JobEvent]:
        with self._lock:
            return sorted(
                self._jobs.values(), key=lambda item: item.created_at, reverse=True
            )

    def cancel(self, job_id: str) -> JobEvent:
        control = self._controls.get(job_id)
        if control is None:
            raise KeyError(job_id)
        control.cancelled.set()
        return self.update(job_id, stage="正在取消")

    def pause(self, job_id: str) -> JobEvent:
        control = self._controls.get(job_id)
        if control is None:
            raise KeyError(job_id)
        control.paused.set()
        job = self.get(job_id)
        payload = {**job.payload, "paused": True}
        return self.update(job_id, stage="已暂停", payload=payload)

    def resume(self, job_id: str) -> JobEvent:
        control = self._controls.get(job_id)
        if control is None:
            raise KeyError(job_id)
        control.paused.clear()
        job = self.get(job_id)
        payload = {**job.payload, "paused": False}
        return self.update(job_id, stage="继续下载", payload=payload)


def error_code_for_message(message: str) -> ErrorCode:
    lowered = message.lower()
    if "out of memory" in lowered or "cuda oom" in lowered:
        return ErrorCode.GPU_OOM
    if "模型尚未安装" in message:
        return ErrorCode.MODEL_NOT_INSTALLED
    if "许可" in message and ("确认" in message or "接受" in message):
        return ErrorCode.LICENSE_NOT_ACCEPTED
    if "空间不足" in message or "可用空间" in message:
        return ErrorCode.DISK_SPACE_LOW
    if "cuda" in lowered and "不可用" in message:
        return ErrorCode.DEVICE_UNAVAILABLE
    if "校验失败" in message or "下载包" in message:
        return ErrorCode.DOWNLOAD_CORRUPT
    return ErrorCode.INVALID_REQUEST
