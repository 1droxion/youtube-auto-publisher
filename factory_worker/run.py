from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

API_URL = "https://natqbwulzzwirbksrvje.supabase.co/functions/v1/factory-worker-api"
OIDC_TOKEN = os.environ.get("FACTORY_OIDC_TOKEN", "").strip()


def api(action: str, **payload):
    if not OIDC_TOKEN:
        raise RuntimeError("FACTORY_OIDC_TOKEN is missing")
    response = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {OIDC_TOKEN}", "Content-Type": "application/json"},
        json={"action": action, **payload},
        timeout=60,
    )
    try:
        data = response.json()
    except Exception:
        data = {"error": response.text}
    if not response.ok:
        raise RuntimeError(data.get("error") or f"Worker API failed: {response.status_code}")
    return data


def download(url: str, path: Path):
    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with path.open("wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)


def has_audio(path: Path) -> bool:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip() or 0)


def render(source: Path, reaction: Path, output: Path):
    source_audio = has_audio(source)
    reaction_audio = has_audio(reaction)

    filter_parts = [
        "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1[base]",
        "[1:v]scale=560:-2:force_original_aspect_ratio=decrease,setsar=1[react]",
        "[base][react]overlay=W-w-32:32:shortest=1[vout]",
    ]

    audio_map = []
    if source_audio and reaction_audio:
        filter_parts.extend([
            "[0:a]volume=0.65[a0]",
            "[1:a]volume=1.15[a1]",
            "[a0][a1]amix=inputs=2:duration=shortest:dropout_transition=2[aout]",
        ])
        audio_map = ["-map", "[aout]"]
    elif source_audio:
        audio_map = ["-map", "0:a:0"]
    elif reaction_audio:
        audio_map = ["-map", "1:a:0"]

    cmd = [
        "ffmpeg", "-y",
        "-i", str(source),
        "-stream_loop", "-1", "-i", str(reaction),
        "-filter_complex", ";".join(filter_parts),
        "-map", "[vout]",
        *audio_map,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
    ]
    if audio_map:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    cmd += ["-movflags", "+faststart", "-shortest", str(output)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "FFmpeg failed")[-4000:])


def upload_signed(signed_url: str, output: Path):
    with output.open("rb") as f:
        response = requests.put(
            signed_url,
            data=f,
            headers={"Content-Type": "video/mp4"},
            timeout=600,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Render upload failed: {response.status_code} {response.text[:500]}")


def main():
    claim = api("claimNextJob")
    job = claim.get("job")
    if not job:
        print("No queued Factory job.")
        return 0

    project_id = job["project_id"]
    print(f"Claimed project {project_id}")

    try:
        api("updateProgress", projectId=project_id, progress=30, status="Preparing")
        assets = api("getProjectAssets", projectId=project_id)

        with tempfile.TemporaryDirectory(prefix="youtube-factory-") as temp_dir:
            temp = Path(temp_dir)
            source = temp / "source.mp4"
            reaction = temp / "reaction.mp4"
            output = temp / "final.mp4"

            print("Downloading source...")
            download(assets["sourceUrl"], source)
            print("Downloading reaction...")
            download(assets["reactionUrl"], reaction)

            api("updateProgress", projectId=project_id, progress=45, status="Rendering")
            print("Rendering 16:9 reaction video...")
            render(source, reaction, output)

            api("updateProgress", projectId=project_id, progress=85, status="Uploading Render")
            upload = api("createRenderUpload", projectId=project_id)
            print("Uploading final render...")
            upload_signed(upload["signedUrl"], output)

            final_duration = duration(output)
            done = api(
                "markRenderComplete",
                projectId=project_id,
                path=upload["path"],
                durationSeconds=final_duration,
            )
            print(json.dumps({"project_id": project_id, "duration": final_duration, "previewUrl": done.get("previewUrl")}, indent=2))
        return 0
    except Exception as exc:
        message = str(exc)
        print(message, file=sys.stderr)
        try:
            api("markRenderFailed", projectId=project_id, error=message)
        except Exception as mark_exc:
            print(f"Could not mark failure: {mark_exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
