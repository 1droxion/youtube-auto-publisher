from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from openai import OpenAI

CHUNK_SECONDS = 600


def _require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Required media tool is not installed: {name}")
    return path


def _has_audio(path: str | Path) -> bool:
    ffprobe = _require_binary("ffprobe")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return bool(result.stdout.strip())


def _extract_audio_chunks(video_path: str | Path, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.glob("chunk_*.mp3"):
        old.unlink(missing_ok=True)

    if not _has_audio(video_path):
        return []

    ffmpeg = _require_binary("ffmpeg")
    pattern = output_dir / "chunk_%04d.mp3"
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "64k",
        "-f",
        "segment",
        "-segment_time",
        str(CHUNK_SECONDS),
        "-reset_timestamps",
        "1",
        str(pattern),
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or exc.stdout or "Audio extraction failed").strip()
        raise RuntimeError(message[-3000:]) from exc
    return sorted(output_dir.glob("chunk_*.mp3"))


def _to_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return value
    try:
        return dict(value)
    except Exception:
        return {"text": str(value)}


def _transcribe_chunk(client: OpenAI, chunk: Path, model: str) -> dict[str, Any]:
    with chunk.open("rb") as audio:
        response = client.audio.transcriptions.create(
            file=audio,
            model=model,
            response_format="verbose_json",
            timestamp_granularities=["segment", "word"],
        )
    return _to_dict(response)


def _shift_timestamps(items: list[dict[str, Any]], offset: float) -> list[dict[str, Any]]:
    shifted: list[dict[str, Any]] = []
    for raw in items or []:
        item = dict(raw)
        if isinstance(item.get("start"), (int, float)):
            item["start"] = float(item["start"]) + offset
        if isinstance(item.get("end"), (int, float)):
            item["end"] = float(item["end"]) + offset
        shifted.append(item)
    return shifted


def transcribe_video(video_path: str | Path, output_dir: str | Path, role: str) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for transcription.")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = output_dir.parent / "audio" / role
    chunks = _extract_audio_chunks(video_path, audio_dir)

    if not chunks:
        result = {
            "role": role,
            "model": None,
            "text": "",
            "segments": [],
            "words": [],
            "chunks": 0,
            "has_audio": False,
        }
        (output_dir / f"{role}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        (output_dir / f"{role}.txt").write_text("", encoding="utf-8")
        return result

    # whisper-1 remains the V1 default because it supports verbose timestamp output.
    model = os.getenv("OPENAI_TRANSCRIBE_MODEL", "whisper-1").strip() or "whisper-1"
    client = OpenAI(api_key=api_key)
    texts: list[str] = []
    segments: list[dict[str, Any]] = []
    words: list[dict[str, Any]] = []

    for index, chunk in enumerate(chunks):
        raw = _transcribe_chunk(client, chunk, model)
        text = str(raw.get("text") or "").strip()
        if text:
            texts.append(text)
        offset = index * CHUNK_SECONDS
        segments.extend(_shift_timestamps(raw.get("segments") or [], offset))
        words.extend(_shift_timestamps(raw.get("words") or [], offset))

    result = {
        "role": role,
        "model": model,
        "text": "\n".join(texts).strip(),
        "segments": segments,
        "words": words,
        "chunks": len(chunks),
        "has_audio": True,
    }
    (output_dir / f"{role}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    (output_dir / f"{role}.txt").write_text(result["text"], encoding="utf-8")
    return result


def transcribe_project(project: dict) -> dict[str, Any]:
    source_path = project.get("normalized_source_path")
    reaction_path = project.get("normalized_reaction_path")
    if not source_path or not reaction_path:
        raise ValueError("Normalize both videos before transcription.")

    project_dir = Path(__file__).resolve().parent / "data" / "projects" / project["id"]
    transcript_dir = project_dir / "transcript"
    source = transcribe_video(source_path, transcript_dir, "source")
    reaction = transcribe_video(reaction_path, transcript_dir, "reaction")
    return {
        "source": source,
        "reaction": reaction,
        "source_transcript_path": str(transcript_dir / "source.json"),
        "reaction_transcript_path": str(transcript_dir / "reaction.json"),
    }
