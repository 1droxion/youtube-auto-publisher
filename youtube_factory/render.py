from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Required media tool is not installed: {name}")
    return path


def render_reaction_layout(project: dict) -> dict:
    source_path = project.get("normalized_source_path")
    reaction_path = project.get("normalized_reaction_path")
    if not source_path or not reaction_path:
        raise ValueError("Normalize both videos before rendering.")

    ffmpeg = _require_binary("ffmpeg")
    project_dir = Path(__file__).resolve().parent / "data" / "projects" / project["id"]
    render_dir = project_dir / "renders"
    render_dir.mkdir(parents=True, exist_ok=True)
    output = render_dir / "reaction_v1.mp4"
    temp = render_dir / ".reaction_v1.tmp.mp4"

    # Main source stays full frame. Reaction is a clean 30% overlay in the
    # upper-right with margin. This is intentionally simple for the first
    # proof-of-core render.
    filter_complex = (
        "[1:v]scale=576:324:force_original_aspect_ratio=decrease,"
        "pad=576:324:(ow-iw)/2:(oh-ih)/2[reaction];"
        "[0:v][reaction]overlay=W-w-48:48:shortest=1[vout];"
        "[0:a]volume=0.55[sourcea];"
        "[1:a]volume=1.0[reactiona];"
        "[sourcea][reactiona]amix=inputs=2:duration=shortest:dropout_transition=2[aout]"
    )

    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(source_path),
        "-i",
        str(reaction_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
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
        "-movflags",
        "+faststart",
        "-shortest",
        str(temp),
    ]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        temp.replace(output)
    except subprocess.CalledProcessError as exc:
        temp.unlink(missing_ok=True)
        message = (exc.stderr or exc.stdout or "Reaction render failed").strip()
        raise RuntimeError(message[-3000:]) from exc

    return {"path": str(output)}
