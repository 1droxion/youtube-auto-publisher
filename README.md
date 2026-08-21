# YouTube Auto Publisher

A separate cloud workflow for videos you **own, created, licensed, or otherwise have permission to reuse**.

## What it does

1. Accepts one public YouTube URL.
2. Downloads the video with `yt-dlp` and converts/remuxes it to MP4.
3. Optionally scans the audio for recognized commercial music with AudD.
4. Depending on the selected music policy, it can:
   - `stop` — stop before upload when recognized music is found (safest default),
   - `mute` — mute the detected music windows and save a cleaned MP4,
   - `ignore` — skip music scanning only when you already own/cleared all audio rights.
5. Uses OpenAI to create a YouTube title, description, tags, thumbnail text, and thumbnail concept.
6. Uses GPT Image to generate a thumbnail and converts it to a YouTube-ready 1280x720 JPEG under 2 MB.
7. Uploads the video and custom thumbnail with the YouTube Data API.
8. Saves a JSON result with the uploaded video ID and URL.

## Important rights note

This project is not a copyright-bypass tool. Music recognition only identifies likely matching tracks; it does **not** determine whether a use is legally licensed or whether a platform claim will occur. The system will not pitch-shift, speed-change, distort, or otherwise modify copyrighted music to evade Content ID. Use `stop` or `mute` for music you do not have rights to, and only process videos you are allowed to download and republish.

The downloader does not implement DRM bypass, private-video bypass, cookie theft, or account-access workarounds.

## GitHub Actions cloud use

Go to **Actions → YouTube Auto Publisher → Run workflow** and provide:

- `source_url`: the public YouTube URL
- `privacy`: `private`, `unlisted`, or `public`
- `music_policy`: `stop`, `mute`, or `ignore`
- `rights_ok`: must be checked to confirm you have reuse rights

The workflow runs on GitHub's cloud runner, so your laptop can be off after the required secrets are configured.

## Required GitHub Secrets

Repository → **Settings → Secrets and variables → Actions**:

- `OPENAI_API_KEY` — used for metadata and thumbnail generation
- `YOUTUBE_TOKEN_JSON` — OAuth credentials created by `connect_youtube.py`
- `AUDD_API_TOKEN` — required for `stop` or `mute` music policies

Never commit any of these values to the repository.

## Connect your YouTube channel once

1. In Google Cloud Console, create/select a project.
2. Enable **YouTube Data API v3**.
3. Configure the OAuth consent screen.
4. Create an OAuth **Desktop app** client.
5. Download the client JSON and save it locally as `client_secret.json` in this project folder.
6. Install dependencies and run:

```bash
python -m pip install -r requirements.txt
python connect_youtube.py
```

7. Sign in to the Google account that owns the target YouTube channel and approve the `youtube.upload` permission.
8. The script creates `youtube_token.json`. Copy the complete contents of that file into the GitHub Actions secret named `YOUTUBE_TOKEN_JSON`.
9. Delete local credential files when you no longer need them, or keep them only in a secure location. They are ignored by git.

Google notes that videos uploaded with newly created/unverified API projects can be forced to **private** until the API project completes YouTube's required audit. This is a Google/YouTube platform restriction, not an error in this project.

## Music recognition

Create an AudD API token and save it as `AUDD_API_TOKEN`. The standard scanner samples the video's audio at configurable intervals. This is useful as a safety check but is not guaranteed to find every song.

Optional environment variables:

- `MUSIC_SCAN_STEP_SECONDS` (default `20`)
- `MUSIC_SAMPLE_SECONDS` (default `12`)
- `MUSIC_MAX_SAMPLES` (default `180`)
- `OPENAI_TEXT_MODEL` (default `gpt-5.6-terra`)
- `OPENAI_IMAGE_MODEL` (default `gpt-image-2`)
- `YOUTUBE_CATEGORY_ID` (default `24`, Entertainment)

## Local test

To build everything without uploading:

```bash
python main.py \
  --url "https://www.youtube.com/watch?v=..." \
  --rights-ok \
  --music-policy stop \
  --privacy private \
  --no-upload
```

For a video whose audio rights you have already cleared:

```bash
python main.py \
  --url "https://www.youtube.com/watch?v=..." \
  --rights-ok \
  --music-policy ignore \
  --privacy private
```

## Output

Temporary downloads go to `work/`. Final files and reports go to `output/`. Both directories are ignored by git.
