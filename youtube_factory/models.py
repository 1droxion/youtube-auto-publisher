from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectStatus(str, Enum):
    DRAFT = "Draft"
    UPLOADED = "Uploaded"
    PREPARING = "Preparing"
    TRANSCRIBING = "Transcribing"
    ANALYZING = "Analyzing"
    EDITING = "Editing"
    RENDERING = "Rendering"
    CREATING_THUMBNAIL = "Creating Thumbnail"
    CREATING_METADATA = "Creating Metadata"
    READY = "Ready"
    UPLOADING = "Uploading"
    PUBLISHED = "Published"
    FAILED = "Failed"


@dataclass
class Project:
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = "Untitled reaction video"
    topic: str = ""
    editing_style: str = "Funny Reaction"
    target_length_minutes: int | None = None
    status: str = ProjectStatus.DRAFT.value
    progress: int = 0
    source_filename: str | None = None
    reaction_filename: str | None = None
    final_duration_seconds: float | None = None
    youtube_upload_status: str = "Not uploaded"
    youtube_video_id: str | None = None
    error: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProcessingJob:
    id: str = field(default_factory=lambda: str(uuid4()))
    project_id: str = ""
    stage: str = ProjectStatus.PREPARING.value
    progress: int = 0
    retry_count: int = 0
    error: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
