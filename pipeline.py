#!/usr/bin/env python3
import base64
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import requests
from PIL import Image
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from openai import OpenAI

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "work"
OUTPUT = ROOT / "output"
WORK.mkdir(exist_ok=True)
OUTPUT.mkdir(exist_ok=True)


def run(cmd):
    print("RUN:", " ".join(str(x) for x in cmd))
    subprocess.run(cmd, check=True)


def ffprobe_duration(path):
    p = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path)
    ], capture_output=True, text=True, check=True)
    return float(p.stdout.strip())


def download_video(url):
    template = str(WORK / "source.%(ext)s")
    run([
        "yt-dlp", "--no-playlist",
        "-f", "bv*+ba/b",
        "--merge-output-format", "mp4",
        "-o", template,
        url,
    ])
    files = sorted(WORK.glob("source.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise RuntimeError("yt-dlp completed but no source file was created.")
    source = files[0]
    if source.suffix.lower() != ".mp4":
        mp4 = WORK / "source.mp4"
        run(["ffmpeg", "-y", "-i", str(source), "-c", "copy", str(mp4)])
        source = mp4
    return source


def extract_sample(video, start, length, output):
    run([
        "ffmpeg", "-y", "-ss", f"{start:.2f}", "-i", str(video),
        "-t", f"{length:.2f}", "-vn", "-ac", "1", "-ar", "44100",
        "-c:a", "mp3", "-b:a", "128k", str(output)
    ])


def recognize_sample(sample_path):
    token = os.getenv("AUDD_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("AUDD_API_TOKEN is required for music_policy stop or mute.")
    with sample_path.open("rb") as f:
        r = requests.post(
            "https://api.audd.io/",
            data={"api_token": token, "return": "timecode"},
            files={"file": f},
            timeout=90,
        )
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "success":
        raise RuntimeError(f"AudD error: {data}")
    return data.get("result")


def scan_music(video):
    duration = ffprobe_duration(video)
    step = max(10.0, float(os.getenv("MUSIC_SCAN_STEP_SECONDS", "20")))
    sample_len = max(6.0, float(os.getenv("MUSIC_SAMPLE_SECONDS", "12")))
    max_samples = max(1, int(os.getenv("MUSIC_MAX_SAMPLES", "180")))
    matches = []
    index = 0
    start = 0.0
    while start < duration and index < max_samples:
        length = min(sample_len, duration - start)
        if length < 5:
            break
        sample = WORK / f"music_sample_{index:04d}.mp3"
        extract_sample(video, start, length, sample)
        result = recognize_sample(sample)
        if result:
            matches.append({
                "window_start": start,
                "window_end": start + length,
                "artist": result.get("artist"),
                "title": result.get("title"),
                "album": result.get("album"),
                "song_link": result.get("song_link"),
                "timecode": result.get("timecode"),
            })
            print("Recognized music:", matches[-1])
        try:
            sample.unlink()
        except FileNotFoundError:
            pass
        index += 1
        start += step
    return matches


def merge_windows(matches, padding=2.0):
    ranges = sorted((max(0.0, m["window_start"] - padding), m["window_end"] + padding) for m in matches)
    merged = []
    for start, end in ranges:
        if not merged or start > merged[-1][1] + 0.5:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return merged


def mute_music_windows(video, matches):
    if not matches:
        return video
    filters = []
    for start, end in merge_windows(matches):
        filters.append(f"volume=enable='between(t,{start:.3f},{end:.3f})':volume=0")
    out = OUTPUT / "cleaned_video.mp4"
    run([
        "ffmpeg", "-y", "-i", str(video),
        "-c:v", "copy", "-af", ",".join(filters),
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)
    ])
    return out


def make_preview_frame(video):
    out = WORK / "preview.jpg"
    duration = ffprobe_duration(video)
    at = min(max(duration * 0.35, 1.0), max(duration - 1.0, 1.0))
    run(["ffmpeg", "-y", "-ss", f"{at:.2f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(out)])
    return out


def get_source_metadata(url):
    p = subprocess.run(["yt-dlp", "--no-playlist", "--skip-download", "--dump-single-json", url], capture_output=True, text=True, check=True)
    data = json.loads(p.stdout)
    return {
        "source_title": data.get("title") or "",
        "source_description": (data.get("description") or "")[:5000],
        "duration": data.get("duration"),
        "uploader": data.get("uploader") or "",
    }


def generate_metadata(url, music_matches):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing.")
    client = OpenAI(api_key=api_key)
    model = os.getenv("OPENAI_TEXT_MODEL", "gpt-5-mini")
    source = get_source_metadata(url)
    prompt = f"""
Create original YouTube publishing metadata for a video the user has rights to reuse.
Do not make copyright claims, do not pretend the user recorded footage if that is not stated, and do not mention bypassing Content ID.
Return JSON only with keys: title, description, tags, thumbnail_text, thumbnail_concept.
Title: <= 90 chars and strong but truthful.
Description: useful, natural, include 3-5 relevant hashtags at the end.
Tags: 10-20 short strings.
Thumbnail text: 2-5 words max.
Thumbnail concept: detailed visual concept suitable for a 16:9 YouTube thumbnail, no logos unless described in source.

Source metadata:
{json.dumps(source, ensure_ascii=False)}
Recognized music scan results (may be empty):
{json.dumps(music_matches, ensure_ascii=False)}
"""
    response = client.responses.create(
        model=model,
        input=prompt,
        text={"format": {"type": "json_object"}},
    )
    return json.loads(response.output_text)


def generate_thumbnail(metadata, video):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    client = OpenAI(api_key=api_key)
    image_model = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
    preview = make_preview_frame(video)
    prompt = (
        "Create a highly clickable professional YouTube thumbnail, 16:9 composition. "
        "It must feel original and cinematic, with clear focal hierarchy and strong facial/object emphasis when appropriate. "
        f"Concept: {metadata.get('thumbnail_concept','')}. "
        f"Include only this short text if text is useful: {metadata.get('thumbnail_text','')}. "
        "Avoid misleading imagery, watermarks, platform UI, copyrighted logos, or tiny unreadable text."
    )
    with preview.open("rb") as img:
        result = client.images.edit(model=image_model, image=img, prompt=prompt, size="1536x1024")
    b64 = result.data[0].b64_json
    raw = WORK / "thumbnail_raw.png"
    raw.write_bytes(base64.b64decode(b64))

    with Image.open(raw).convert("RGB") as image:
        image = image.resize((1280, 720), Image.Resampling.LANCZOS)
        out = OUTPUT / "thumbnail.jpg"
        quality = 92
        while True:
            image.save(out, "JPEG", quality=quality, optimize=True)
            if out.stat().st_size <= 1_950_000 or quality <= 60:
                break
            quality -= 5
    return out


def youtube_credentials():
    raw = os.getenv("YOUTUBE_TOKEN_JSON", "").strip()
    if not raw:
        local = Path("youtube_token.json")
        if local.exists():
            raw = local.read_text(encoding="utf-8")
    if not raw:
        raise RuntimeError("YOUTUBE_TOKEN_JSON is missing. Run connect_youtube.py first.")
    info = json.loads(raw)
    creds = Credentials.from_authorized_user_info(info, ["https://www.googleapis.com/auth/youtube.upload"])
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def upload_to_youtube(video, thumbnail, metadata, privacy):
    youtube = build("youtube", "v3", credentials=youtube_credentials(), cache_discovery=False)
    body = {
        "snippet": {
            "title": metadata["title"][:100],
            "description": metadata["description"][:5000],
            "tags": metadata.get("tags", [])[:30],
            "categoryId": os.getenv("YOUTUBE_CATEGORY_ID", "24"),
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Upload progress: {int(status.progress() * 100)}%")
    video_id = response["id"]
    youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumbnail))).execute()
    return {"video_id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}"}


def process(url, rights_ok, music_policy, privacy, upload=True):
    if not rights_ok:
        raise RuntimeError("Rights confirmation is required. Only process videos you own or have permission/license to reuse.")
    if music_policy not in {"stop", "mute", "ignore"}:
        raise ValueError("music_policy must be stop, mute, or ignore")
    if privacy not in {"private", "unlisted", "public"}:
        raise ValueError("privacy must be private, unlisted, or public")

    for path in WORK.glob("source.*"):
        path.unlink(missing_ok=True)

    source = download_video(url)
    matches = [] if music_policy == "ignore" else scan_music(source)
    report = {"source_url": url, "music_policy": music_policy, "music_matches": matches}
    (OUTPUT / "music_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    if matches and music_policy == "stop":
        raise RuntimeError("Recognized music was found. Upload stopped. Review output/music_report.json or rerun with music_policy=mute only if muting is appropriate.")

    final_video = mute_music_windows(source, matches) if music_policy == "mute" else source
    if final_video == source:
        copied = OUTPUT / "final_video.mp4"
        shutil.copy2(source, copied)
        final_video = copied

    metadata = generate_metadata(url, matches)
    (OUTPUT / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    thumbnail = generate_thumbnail(metadata, final_video)

    result = {
        "source_url": url,
        "video": str(final_video),
        "thumbnail": str(thumbnail),
        "metadata": metadata,
        "music_matches": matches,
        "uploaded": False,
    }
    if upload:
        result.update(upload_to_youtube(final_video, thumbnail, metadata, privacy))
        result["uploaded"] = True
    (OUTPUT / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result
