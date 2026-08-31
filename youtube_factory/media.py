from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

BASE_DIR = Path(__file__).resolve().parent / "data" / "projects"
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov"}
DEFAULT_MAX_BYTES = 4 * 1024 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class SavedUpload:
    filename: str
    path: str
    size_bytes: int


def max_upload_bytes() -> int:
    raw = os.getenv("YOUTUBE_FACTORY_MAX_UPLOAD_GB", "4").strip()
    try:
        gb = max(1.0, float(raw))
    except ValueError:
        gb = 4.0
    return int(gb * 1024 * 1024 * 1024)


def validate_video_filename(filename: str | None) -> str:
    if not filename:
        raise ValueError("Video filename is missing.")
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_VIDEO_EXTENSIONS:
        raise ValueError("Only MP4 and MOV video uploads are supported in V1.")
    return suffix


async def save_project_upload(project_id: str, role: str, upload: UploadFile) -> SavedUpload:
    if role not in {"source", "reaction"}:
        raise ValueError("Upload role must be source or reaction.")

    suffix = validate_video_filename(upload.filename)
    project_dir = BASE_DIR / project_id / "original"
    project_dir.mkdir(parents=True, exist_ok=True)

    final_path = project_dir / f"{role}{suffix}"
    temp_path = project_dir / f".{role}{suffix}.uploading"
    limit = max_upload_bytes()
    total = 0

    try:
        with temp_path.open("wb") as output:
            while True:
                chunk = await upload.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise ValueError(
                        f"{role.title()} video is too large. Maximum upload size is "
                        f"{limit / (1024 ** 3):.1f} GB."
                    )
                output.write(chunk)

        if total == 0:
            raise ValueError(f"{role.title()} video is empty.")

        # Remove an older version with the other supported extension so each
        # project has exactly one source and one reaction original.
        for extension in ALLOWED_VIDEO_EXTENSIONS:
            old_path = project_dir / f"{role}{extension}"
            if old_path != final_path:
                old_path.unlink(missing_ok=True)

        temp_path.replace(final_path)
        return SavedUpload(
            filename=Path(upload.filename or final_path.name).name,
            path=str(final_path),
            size_bytes=total,
        )
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
