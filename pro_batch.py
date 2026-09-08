#!/usr/bin/env python3
import base64
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image
from openai import OpenAI

from pipeline import (
    OUTPUT,
    WORK,
    ffprobe_duration,
    generate_thumbnail,
    merge_windows,
    run,
    scan_music,
    upload_to_youtube,
)

BATCH_WORK = WORK / "pro_batch"
BATCH_WORK.mkdir(parents=True, exist_ok=True)

WIDTH = 1920
HEIGHT = 1080
FPS = 30
MAX_CLIPS = max(2, min(20, int(os.getenv("PRO_BATCH_MAX_CLIPS", "20"))))
TEXT_MODEL = os.getenv("OPENAI_TEXT_MODEL", "gpt-5-mini")
IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
TRANSCRIBE_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "whisper-1")


def _client():
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is missing.")
    return OpenAI(api_key=key)


def parse_urls(raw):
    chunks = re.split(r"[\n\r;,|]+", str(raw or ""))
    urls = []
    seen = set()
    for chunk in chunks:
        value = chunk.strip()
        if not value:
            continue
        if not value.startswith(("http://", "https://")):
            raise ValueError(f"Invalid source URL: {value}")
        if value not in seen:
            seen.add(value)
            urls.append(value)
    if len(urls) < 2:
        raise ValueError("Pro Batch needs at least 2 source URLs.")
    if len(urls) > MAX_CLIPS:
        raise ValueError(f"Pro Batch supports up to {MAX_CLIPS} source URLs per video.")
    return urls


def source_metadata(url, index):
    p = subprocess.run(
        ["yt-dlp", "--no-playlist", "--skip-download", "--dump-single-json", url],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(p.stdout)
    return {
        "index": index,
        "url": url,
        "title": data.get("title") or f"Clip {index + 1}",
        "description": (data.get("description") or "")[:1200],
        "duration": float(data.get("duration") or 0),
        "uploader": data.get("uploader") or "",
    }


def choose_order(items):
    if os.getenv("PRO_BATCH_AI_ORDER", "1").strip().lower() in {"0", "false", "no"}:
        return list(range(len(items)))

    prompt = f"""
You are editing one professional long-form YouTube video from a set of short horizontal clips.
Choose the most coherent high-retention order. Prefer a strong hook first, clear progression in the middle,
and a satisfying payoff/end. Never invent facts. Use every clip exactly once unless two entries are obvious duplicates.
Return JSON only: {{"order":[0,1,...],"reason":"short explanation"}}.

Clips:
{json.dumps(items, ensure_ascii=False)}
"""
    try:
        response = _client().responses.create(
            model=TEXT_MODEL,
            input=prompt,
            text={"format": {"type": "json_object"}},
        )
        data = json.loads(response.output_text)
        raw = data.get("order") or []
        order = []
        seen = set()
        for value in raw:
            try:
                idx = int(value)
            except Exception:
                continue
            if 0 <= idx < len(items) and idx not in seen:
                seen.add(idx)
                order.append(idx)
        for idx in range(len(items)):
            if idx not in seen:
                order.append(idx)
        return order
    except Exception as exc:
        print(f"AI ordering failed; preserving input order: {exc}")
        return list(range(len(items)))


def download_clip(url, index):
    for old in BATCH_WORK.glob(f"clip_{index:02d}.*"):
        old.unlink(missing_ok=True)
    template = str(BATCH_WORK / f"clip_{index:02d}.%(ext)s")
    run([
        "yt-dlp", "--no-playlist",
        "-f", "bv*+ba/b",
        "--merge-output-format", "mp4",
        "-o", template,
        url,
    ])
    files = sorted(BATCH_WORK.glob(f"clip_{index:02d}.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise RuntimeError(f"No downloaded file was created for clip {index + 1}.")
    return files[0]


def mute_music_windows_to(video, matches, out):
    if not matches:
        shutil.copy2(video, out)
        return out
    filters = []
    for start, end in merge_windows(matches):
        filters.append(f"volume=enable='between(t,{start:.3f},{end:.3f})':volume=0")
    run([
        "ffmpeg", "-y", "-i", str(video),
        "-c:v", "copy", "-af", ",".join(filters),
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out),
    ])
    return out


def normalize_clip(video, index):
    duration = ffprobe_duration(video)
    fade_out = max(0.0, duration - 0.20)
    out = BATCH_WORK / f"norm_{index:02d}.mp4"
    # Every source is converted to the same 16:9 H.264/AAC profile so concat is reliable.
    # A slow, frame-evaluated scale creates a subtle push-in / pull-out instead of a static crop.
    zoom = "1+0.028*(0.5+0.5*sin(2*PI*t/9))"
    vf = (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},"
        f"scale=w='{WIDTH}*({zoom})':h='{HEIGHT}*({zoom})':eval=frame,"
        f"crop={WIDTH}:{HEIGHT},"
        "eq=contrast=1.035:saturation=1.045:brightness=0.005,"
        "unsharp=5:5:0.35:3:3:0.0,"
        f"fps={FPS},format=yuv420p,"
        "fade=t=in:st=0:d=0.20,"
        f"fade=t=out:st={fade_out:.3f}:d=0.20"
    )
    af = (
        "loudnorm=I=-16:TP=-1.5:LRA=11,"
        "afade=t=in:st=0:d=0.10,"
        f"afade=t=out:st={max(0.0, duration - 0.10):.3f}:d=0.10"
    )
    run([
        "ffmpeg", "-y", "-i", str(video),
        "-vf", vf,
        "-af", af,
        "-c:v", "libx264", "-preset", "medium", "-crf", "19",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(out),
    ])
    return out


def concat_clips(clips):
    listing = BATCH_WORK / "concat.txt"
    lines = []
    for clip in clips:
        safe = str(clip.resolve()).replace("'", "'\\''")
        lines.append(f"file '{safe}'")
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = BATCH_WORK / "assembled.mp4"
    run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
        "-c", "copy", "-movflags", "+faststart", str(out),
    ])
    return out


def _obj_to_dict(value):
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return {}


def transcribe(video):
    audio = BATCH_WORK / "speech.mp3"
    run([
        "ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "libmp3lame", "-b:a", "64k", str(audio),
    ])
    with audio.open("rb") as f:
        result = _client().audio.transcriptions.create(
            model=TRANSCRIBE_MODEL,
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    data = _obj_to_dict(result)
    text = str(data.get("text") or getattr(result, "text", "") or "").strip()
    segments = data.get("segments") or getattr(result, "segments", None) or []
    normalized = []
    for segment in segments:
        item = _obj_to_dict(segment)
        try:
            start = float(item.get("start", 0))
            end = float(item.get("end", start + 1))
        except Exception:
            continue
        phrase = str(item.get("text") or "").strip()
        if phrase:
            normalized.append({"start": start, "end": max(end, start + 0.3), "text": phrase})
    if not normalized and text:
        normalized = [{"start": 0.0, "end": ffprobe_duration(video), "text": text}]
    return text, normalized


def srt_time(seconds):
    ms = max(0, int(round(seconds * 1000)))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, milli = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{milli:03d}"


def split_caption_segment(segment, max_words=10):
    words = str(segment["text"]).split()
    if len(words) <= max_words:
        return [segment]
    pieces = [words[i:i + max_words] for i in range(0, len(words), max_words)]
    total = max(0.3, segment["end"] - segment["start"])
    weight = sum(len(x) for x in pieces)
    cursor = segment["start"]
    out = []
    for i, piece in enumerate(pieces):
        duration = total * (len(piece) / weight)
        end = segment["end"] if i == len(pieces) - 1 else cursor + duration
        out.append({"start": cursor, "end": end, "text": " ".join(piece)})
        cursor = end
    return out


def write_srt(segments):
    srt = BATCH_WORK / "captions.srt"
    rows = []
    index = 1
    for segment in segments:
        for piece in split_caption_segment(segment):
            rows.extend([
                str(index),
                f"{srt_time(piece['start'])} --> {srt_time(piece['end'])}",
                piece["text"],
                "",
            ])
            index += 1
    srt.write_text("\n".join(rows), encoding="utf-8")
    return srt


def burn_captions(video, segments):
    if not segments:
        return video
    srt = write_srt(segments)
    escaped = str(srt.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    style = (
        "FontName=DejaVu Sans,FontSize=21,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00101010,BorderStyle=1,Outline=3,Shadow=1,"
        "Alignment=2,MarginV=58"
    )
    out = BATCH_WORK / "captioned.mp4"
    run([
        "ffmpeg", "-y", "-i", str(video),
        "-vf", f"subtitles='{escaped}':force_style='{style}'",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "copy", "-movflags", "+faststart", str(out),
    ])
    return out


def plan_broll(transcript, duration, count):
    if count <= 0 or duration < 30:
        return []
    prompt = f"""
Create {count} useful visual cutaway ideas for a professional YouTube video.
The cutaways will cover the main video for about 2.5 seconds while the original audio keeps playing.
They must directly support what is being said at that moment, not be random decoration.
Avoid real celebrity likenesses, copyrighted characters, logos, watermarks, UI screenshots, and text-heavy images.
Return JSON only: {{"visuals":[{{"time":42.0,"prompt":"..."}}]}}.
Times must be between 12 seconds and {max(12, duration - 10):.1f} seconds and spread across the video.

Transcript:
{transcript[:14000]}
"""
    try:
        response = _client().responses.create(
            model=TEXT_MODEL,
            input=prompt,
            text={"format": {"type": "json_object"}},
        )
        data = json.loads(response.output_text)
        visuals = []
        for item in data.get("visuals") or []:
            try:
                at = float(item.get("time"))
            except Exception:
                continue
            p = str(item.get("prompt") or "").strip()
            if p and 8 <= at <= max(8, duration - 5):
                visuals.append({"time": at, "prompt": p})
        return visuals[:count]
    except Exception as exc:
        print(f"B-roll planning failed; continuing without generated cutaways: {exc}")
        return []


def generate_broll_images(visuals):
    images = []
    client = _client()
    for i, visual in enumerate(visuals):
        prompt = (
            "Create a cinematic 16:9 YouTube B-roll cutaway. Photorealistic or polished illustrative style, "
            "clean composition, strong depth, no text, no logo, no watermark. "
            f"Scene: {visual['prompt']}"
        )
        try:
            result = client.images.generate(model=IMAGE_MODEL, prompt=prompt, size="1536x1024")
            raw = BATCH_WORK / f"broll_{i:02d}.png"
            raw.write_bytes(base64.b64decode(result.data[0].b64_json))
            out = BATCH_WORK / f"broll_{i:02d}.jpg"
            with Image.open(raw).convert("RGB") as im:
                # Center-crop 3:2 source to 16:9 without stretching.
                target_ratio = 16 / 9
                ratio = im.width / im.height
                if ratio > target_ratio:
                    new_w = int(im.height * target_ratio)
                    left = (im.width - new_w) // 2
                    im = im.crop((left, 0, left + new_w, im.height))
                elif ratio < target_ratio:
                    new_h = int(im.width / target_ratio)
                    top = (im.height - new_h) // 2
                    im = im.crop((0, top, im.width, top + new_h))
                im = im.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
                im.save(out, "JPEG", quality=92, optimize=True)
            images.append({**visual, "path": out})
        except Exception as exc:
            print(f"B-roll image {i + 1} failed; skipping it: {exc}")
    return images


def overlay_broll(video, visuals):
    if not visuals:
        return video
    duration = ffprobe_duration(video)
    cmd = ["ffmpeg", "-y", "-i", str(video)]
    for item in visuals:
        cmd.extend(["-loop", "1", "-framerate", str(FPS), "-i", str(item["path"])])

    filters = []
    previous = "[0:v]"
    for idx, item in enumerate(visuals, start=1):
        image_label = f"b{idx}"
        out_label = f"v{idx}"
        filters.append(f"[{idx}:v]scale={WIDTH}:{HEIGHT},setsar=1[{image_label}]")
        start = max(0.0, float(item["time"]))
        end = min(duration, start + 2.6)
        filters.append(f"{previous}[{image_label}]overlay=0:0:enable='between(t,{start:.3f},{end:.3f})'[{out_label}]")
        previous = f"[{out_label}]"

    out = BATCH_WORK / "with_broll.mp4"
    cmd.extend([
        "-filter_complex", ";".join(filters),
        "-map", previous, "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "copy", "-t", f"{duration:.3f}", "-movflags", "+faststart", str(out),
    ])
    run(cmd)
    return out


def generate_batch_metadata(items, transcript):
    compact = [{
        "title": x["title"],
        "uploader": x["uploader"],
        "duration": x["duration"],
    } for x in items]
    prompt = f"""
Create high-quality YouTube publishing metadata for one original edited long-form video assembled from rights-cleared source clips.
Use the transcript as the main truth source. If the narration is mostly Hindi/Hinglish, write a natural Hindi/Hinglish title and description;
otherwise use the transcript's main language. Optimize for real click-through and search without false claims or fake urgency.
Return JSON only with keys: title, description, tags, thumbnail_text, thumbnail_concept.
Title <= 90 characters. Description should have a strong first 2 lines, a useful summary, and 3-5 relevant hashtags at the end.
Tags: 12-20 short strings. Thumbnail text: 2-5 words max. Thumbnail concept: one strong 16:9 visual idea.
Do not claim the creator filmed footage unless the transcript/source says that. Do not mention automation or AI.

Source clip metadata:
{json.dumps(compact, ensure_ascii=False)}

Transcript:
{transcript[:18000]}
"""
    response = _client().responses.create(
        model=TEXT_MODEL,
        input=prompt,
        text={"format": {"type": "json_object"}},
    )
    return json.loads(response.output_text)


def process_batch(raw_urls, rights_ok, music_policy, privacy, upload=True, broll_count=2):
    if not rights_ok:
        raise RuntimeError("Rights confirmation is required for every source clip.")
    if music_policy not in {"stop", "mute", "ignore"}:
        raise ValueError("music_policy must be stop, mute, or ignore")
    if privacy not in {"private", "unlisted", "public"}:
        raise ValueError("privacy must be private, unlisted, or public")

    shutil.rmtree(BATCH_WORK, ignore_errors=True)
    BATCH_WORK.mkdir(parents=True, exist_ok=True)
    urls = parse_urls(raw_urls)
    print(f"Preparing professional YouTube batch from {len(urls)} clips.")

    metadata_items = [source_metadata(url, i) for i, url in enumerate(urls)]
    order = choose_order(metadata_items)
    ordered_items = [metadata_items[i] for i in order]
    print("Clip order:", order)

    normalized = []
    music_report = []
    for out_index, original_index in enumerate(order):
        item = metadata_items[original_index]
        source = download_clip(item["url"], original_index)
        matches = [] if music_policy == "ignore" else scan_music(source)
        music_report.append({"source": item["url"], "matches": matches})
        if matches and music_policy == "stop":
            raise RuntimeError(f"Recognized music found in clip {original_index + 1}; batch stopped before upload.")
        cleaned = source
        if matches and music_policy == "mute":
            cleaned = BATCH_WORK / f"clean_{original_index:02d}.mp4"
            mute_music_windows_to(source, matches, cleaned)
        normalized.append(normalize_clip(cleaned, out_index))

    assembled = concat_clips(normalized)
    transcript, segments = transcribe(assembled)
    (OUTPUT / "pro_batch_transcript.txt").write_text(transcript, encoding="utf-8")
    captioned = burn_captions(assembled, segments)

    count = max(0, min(3, int(broll_count)))
    visuals = plan_broll(transcript, ffprobe_duration(captioned), count)
    generated_visuals = generate_broll_images(visuals)
    final_video = overlay_broll(captioned, generated_visuals)
    final_path = OUTPUT / "pro_batch_final.mp4"
    shutil.copy2(final_video, final_path)

    metadata = generate_batch_metadata(ordered_items, transcript)
    (OUTPUT / "pro_batch_metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUTPUT / "pro_batch_music_report.json").write_text(json.dumps(music_report, indent=2, ensure_ascii=False), encoding="utf-8")
    thumbnail = generate_thumbnail(metadata, final_path)

    result = {
        "sources": urls,
        "order": order,
        "video": str(final_path),
        "thumbnail": str(thumbnail),
        "metadata": metadata,
        "broll": [{"time": x["time"], "prompt": x["prompt"]} for x in generated_visuals],
        "uploaded": False,
    }
    if upload:
        result.update(upload_to_youtube(final_path, thumbnail, metadata, privacy))
        result["uploaded"] = True
    (OUTPUT / "pro_batch_result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result
