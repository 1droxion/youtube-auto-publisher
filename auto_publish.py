#!/usr/bin/env python3
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

import pipeline

ROOT = Path(__file__).resolve().parent
QUEUE_FILE = ROOT / "source_urls.txt"
STATE_FILE = ROOT / "data" / "published_urls.json"


def load_queue():
    if not QUEUE_FILE.exists():
        return []

    urls = []
    for raw in QUEUE_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("RIGHTS_OK|"):
            print(f"Skipping line without RIGHTS_OK confirmation: {line[:120]}")
            continue
        url = line.split("|", 1)[1].strip()
        if url:
            urls.append(url)
    return urls


def load_state():
    if not STATE_FILE.exists():
        return {"published": []}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"published": []}
    if not isinstance(data, dict) or not isinstance(data.get("published"), list):
        return {"published": []}
    return data


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def generate_hindi_movie_explain_metadata(url, music_matches):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing.")

    client = OpenAI(api_key=api_key)
    model = os.getenv("OPENAI_TEXT_MODEL", "gpt-5.6-terra")
    source = pipeline.get_source_metadata(url)

    prompt = f"""
You are packaging a rights-cleared Hindi/Hinglish movie-explanation video for YouTube.
Create ORIGINAL publishing metadata. Do not copy the source title word-for-word.
Do not claim the uploader owns a movie, studio footage, music, or characters unless the source metadata explicitly says so.
Do not mention bypassing Content ID or copyright systems.

Return JSON only with keys: title, description, tags, thumbnail_text, thumbnail_concept.

TITLE RULES:
- Maximum 90 characters.
- Strong curiosity hook, truthful, natural Hindi/Hinglish.
- Make the core story/conflict obvious.
- When useful, end naturally with "Movie Explained in Hindi" or "Hindi Explanation".
- No fake claims such as "true story" unless supported by source metadata.

DESCRIPTION RULES:
- Write 2-4 short paragraphs in natural Hindi/Hinglish.
- Briefly describe the premise without spoiling everything.
- Add a simple subscribe/comment CTA.
- End with 3-5 relevant hashtags.
- Do not invent cast names, movie names, dates, awards, or facts that are not in the source metadata.

TAGS RULES:
- 12-20 concise Hindi/English search terms relevant to movie explanation.
- No unrelated trending keywords.

THUMBNAIL RULES:
- thumbnail_text must be only 2-4 punchy Hindi/Hinglish words.
- thumbnail_concept must describe one clear cinematic 16:9 scene with one dominant subject, strong emotion, high contrast, and large readable composition.
- No YouTube UI, watermarks, misleading celebrities, studio logos, or unrelated characters.

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


def main():
    urls = load_queue()
    state = load_state()
    already = {item.get("source_url") for item in state["published"] if isinstance(item, dict)}
    next_url = next((url for url in urls if url not in already), None)

    if not next_url:
        print("No new rights-cleared source URL is waiting in source_urls.txt. Nothing to publish.")
        return

    # Use the Hindi movie-explain metadata profile for scheduled jobs.
    pipeline.generate_metadata = generate_hindi_movie_explain_metadata

    music_policy = os.getenv("AUTO_MUSIC_POLICY", "stop").strip().lower()
    privacy = os.getenv("AUTO_PRIVACY", "public").strip().lower()

    result = pipeline.process(
        url=next_url,
        rights_ok=True,
        music_policy=music_policy,
        privacy=privacy,
        upload=True,
    )

    state["published"].append(
        {
            "source_url": next_url,
            "video_id": result.get("video_id"),
            "youtube_url": result.get("url"),
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    save_state(state)
    print(f"Published and recorded source: {next_url}")


if __name__ == "__main__":
    main()
