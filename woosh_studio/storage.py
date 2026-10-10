from __future__ import annotations

import json
import os
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

from .schemas import JobEvent, JobStatus, RuntimeSettings, utc_now


class AtomicJsonStore:
    @staticmethod
    def write(path: Path, data: dict[str, Any], backup: bool = True) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        backup_path = path.with_suffix(path.suffix + ".bak")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        if backup and path.exists():
            shutil.copy2(path, backup_path)
        os.replace(temporary, path)

    @staticmethod
    def read(path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            backup_path = path.with_suffix(path.suffix + ".bak")
            if not backup_path.exists():
                raise
            return json.loads(backup_path.read_text(encoding="utf-8"))


class LibraryDatabase:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = sqlite3.connect(self.path)
            connection.row_factory = sqlite3.Row
            try:
                yield connection
                connection.commit()
            finally:
                connection.close()

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recent_projects (
                    path TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    opened_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS license_acceptance (
                    model_id TEXT NOT NULL,
                    release TEXT NOT NULL,
                    accepted_at TEXT NOT NULL,
                    PRIMARY KEY(model_id, release)
                );
                CREATE TABLE IF NOT EXISTS custom_models (
                    id TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    family TEXT NOT NULL,
                    registered_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS speech_items (
                    job_id TEXT NOT NULL, line_id TEXT NOT NULL, locale TEXT NOT NULL,
                    project_path TEXT NOT NULL, fingerprint TEXT, status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 1, data TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(job_id, line_id, locale)
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    progress REAL NOT NULL,
                    stage TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "UPDATE speech_items SET status = 'interrupted' WHERE status IN ('queued', 'running')"
            )
            connection.execute(
                "UPDATE jobs SET status = ?, stage = ?, updated_at = ? "
                "WHERE status IN (?, ?, ?, ?)",
                (
                    JobStatus.INTERRUPTED.value,
                    "应用已重新启动",
                    utc_now().isoformat(),
                    JobStatus.QUEUED.value,
                    JobStatus.LOADING.value,
                    JobStatus.RUNNING.value,
                    JobStatus.RENDERING.value,
                ),
            )

    def get_settings(self) -> RuntimeSettings:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = 'runtime'"
            ).fetchone()
        if row is None:
            return RuntimeSettings()
        return RuntimeSettings.model_validate_json(row["value"])

    def save_settings(self, settings: RuntimeSettings) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO settings(key, value) VALUES('runtime', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (settings.model_dump_json(),),
            )

    def remember_project(self, path: Path, name: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO recent_projects(path, name, opened_at) VALUES(?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET name = excluded.name, "
                "opened_at = excluded.opened_at",
                (str(path), name, utc_now().isoformat()),
            )

    def recent_projects(self, limit: int = 12) -> list[dict[str, str]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT path, name, opened_at FROM recent_projects "
                "ORDER BY opened_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def forget_project(self, path: Path) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM recent_projects WHERE path = ?",
                (str(path),),
            )
        return cursor.rowcount > 0

    def accept_license(self, model_id: str, release: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO license_acceptance(model_id, release, accepted_at) "
                "VALUES(?, ?, ?) ON CONFLICT(model_id, release) "
                "DO UPDATE SET accepted_at = excluded.accepted_at",
                (model_id, release, utc_now().isoformat()),
            )

    def license_accepted(self, model_id: str, release: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM license_acceptance WHERE model_id = ? AND release = ?",
                (model_id, release),
            ).fetchone()
        return row is not None

    def register_custom_model(self, model_id: str, path: Path, family: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO custom_models(id, path, family, registered_at) "
                "VALUES(?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "path = excluded.path, family = excluded.family, "
                "registered_at = excluded.registered_at",
                (model_id, str(path), family, utc_now().isoformat()),
            )

    def custom_models(self) -> list[dict[str, str]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, path, family, registered_at FROM custom_models"
            ).fetchall()
        return [dict(row) for row in rows]

    def save_job(self, job: JobEvent) -> None:
        payload = json.dumps(job.payload, ensure_ascii=False)
        result = json.dumps(job.result, ensure_ascii=False) if job.result else None
        error = job.error.model_dump_json() if job.error else None
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs(
                    id, kind, status, payload, result, error, progress, stage,
                    created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    payload = excluded.payload,
                    result = excluded.result,
                    error = excluded.error,
                    progress = excluded.progress,
                    stage = excluded.stage,
                    updated_at = excluded.updated_at
                """,
                (
                    job.id,
                    job.kind.value,
                    job.status.value,
                    payload,
                    result,
                    error,
                    job.progress,
                    job.stage,
                    job.created_at.isoformat(),
                    job.updated_at.isoformat(),
                ),
            )

    def recent_jobs(self, limit: int = 100) -> list[JobEvent]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            for key in ("payload", "result", "error"):
                data[key] = json.loads(data[key]) if data[key] else None
            result.append(JobEvent.model_validate(data))
        return result

    def save_speech_item(
        self, job_id, line_id, locale, project_path, status, fingerprint=None, **data
    ):
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO speech_items(job_id,line_id,locale,project_path,status,fingerprint,data,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(job_id,line_id,locale) DO UPDATE SET "
                "status=excluded.status,fingerprint=excluded.fingerprint,data=excluded.data,updated_at=excluded.updated_at",
                (
                    job_id,
                    line_id,
                    locale,
                    str(Path(project_path).resolve()),
                    status,
                    fingerprint,
                    json.dumps(data, ensure_ascii=False),
                    utc_now().isoformat(),
                ),
            )

    def speech_items(self, project_path=None, job_id=None, status=None):
        clauses, values = [], []
        for key, value in (
            (
                "project_path",
                str(Path(project_path).resolve()) if project_path else None,
            ),
            ("job_id", job_id),
            ("status", status),
        ):
            if value is not None:
                clauses.append(key + " = ?")
                values.append(value)
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM speech_items"
                + (" WHERE " + " AND ".join(clauses) if clauses else "")
                + " ORDER BY updated_at",
                values,
            ).fetchall()
        return [{**dict(row), "data": json.loads(row["data"])} for row in rows]

    def sfx_batches(self, project_path):
        import os

        key = os.path.normcase(str(Path(project_path).resolve()))
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id,payload,result FROM jobs WHERE kind='generation' AND result IS NOT NULL ORDER BY created_at"
            ).fetchall()
        groups = []
        for row in rows:
            try:
                payload = json.loads(row["payload"])
                result = json.loads(row["result"])
                if (
                    os.path.normcase(
                        str(Path(payload.get("project_path", "")).resolve())
                    )
                    == key
                ):
                    groups.append((row["id"], result.get("asset_ids", [])))
            except (ValueError, TypeError):
                continue
        return groups
