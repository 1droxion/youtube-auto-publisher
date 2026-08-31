from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .models import ProcessingJob, Project, utc_now


class JsonStore:
    """Small persistent store for V1 development.

    It is intentionally isolated behind one class so it can be replaced by
    Supabase/Postgres without changing dashboard or pipeline code later.
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or Path(__file__).resolve().parent / "data" / "factory.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if not self.path.exists():
            self._write({"projects": {}, "jobs": {}})

    def _read(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {"projects": {}, "jobs": {}}

    def _write(self, data: dict[str, Any]) -> None:
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temp.replace(self.path)

    def create_project(self, *, name: str, topic: str = "", target_length_minutes: int | None = None) -> dict[str, Any]:
        project = Project(name=name.strip() or "Untitled reaction video", topic=topic.strip(), target_length_minutes=target_length_minutes)
        with self._lock:
            data = self._read()
            data["projects"][project.id] = project.to_dict()
            self._write(data)
        return project.to_dict()

    def list_projects(self) -> list[dict[str, Any]]:
        with self._lock:
            projects = list(self._read()["projects"].values())
        return sorted(projects, key=lambda item: item.get("created_at", ""), reverse=True)

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._read()["projects"].get(project_id)

    def update_project(self, project_id: str, **changes: Any) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            project = data["projects"].get(project_id)
            if project is None:
                raise KeyError(f"Unknown project: {project_id}")
            project.update(changes)
            project["updated_at"] = utc_now()
            data["projects"][project_id] = project
            self._write(data)
            return project

    def create_job(self, project_id: str, stage: str, progress: int = 0) -> dict[str, Any]:
        if not self.get_project(project_id):
            raise KeyError(f"Unknown project: {project_id}")
        job = ProcessingJob(project_id=project_id, stage=stage, progress=max(0, min(100, progress)))
        with self._lock:
            data = self._read()
            data["jobs"][job.id] = job.to_dict()
            self._write(data)
        return job.to_dict()

    def list_jobs(self, project_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            jobs = list(self._read()["jobs"].values())
        if project_id:
            jobs = [job for job in jobs if job.get("project_id") == project_id]
        return sorted(jobs, key=lambda item: item.get("created_at", ""), reverse=True)
