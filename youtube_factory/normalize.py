from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


def _require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Required media tool is not installed: {name}")
    return path


def probe_video(path: str | Path) -> dict:
    ffprobe = _require_binary("ffprobe")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate,codec_name:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def normalize_video(input_path: str | Path, output_path: str | Path) -> dict:
    ffmpeg = _require_binary("ffmpeg")
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(".tmp.mp4")

    # Fit inside 1920x1080 without stretching, then pad to exact 16:9.
    video_filter = (
        "scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
        "setsar=1,fps=30"
    )

    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        video_filter,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(temp_path),
    ]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        temp_path.replace(output_path)
    except subprocess.CalledProcessError as exc:
        temp_path.unlink(missing_ok=True)
        message = (exc.stderr or exc.stdout or "FFmpeg normalization failed").strip()
        raise RuntimeError(message[-3000:]) from exc

    info = probe_video(output_path)
    duration = float(info.get("format", {}).get("duration") or 0)
    return {
        "path": str(output_path),
        "duration_seconds": duration,
        "probe": info,
    }


def normalize_project(project: dict) -> dict:
    project_id = project["id"]
    source_path = project.get("source_path")
    reaction_path = project.get("reaction_path")
    if not source_path or not reaction_path:
        raise ValueError("Both source and reaction videos must be uploaded first.")

    base = Path(__file__).resolve().parent / "data" / "projects" / project_id / "normalized"
    source = normalize_video(source_path, base / "source.mp4")
    reaction = normalize_video(reaction_path, base / "reaction.mp4")
    return {"source": source, "reaction": reaction}
