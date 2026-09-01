#!/usr/bin/env python3
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
CLIENT_FILE = Path("client_secret.json")
TOKEN_FILE = Path("youtube_token.json")


def main():
    if not CLIENT_FILE.exists():
        raise SystemExit("Missing client_secret.json. Download an OAuth Desktop client JSON from Google Cloud first.")

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")

    channel_name = None
    try:
        youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
        response = youtube.channels().list(part="snippet", mine=True).execute()
        items = response.get("items") or []
        if items:
            channel_name = items[0].get("snippet", {}).get("title")
    except Exception as exc:
        print(f"Connected, but channel name check failed: {exc}")

    print(f"Saved {TOKEN_FILE}.")
    if channel_name:
        print(f"CONNECTED CHANNEL: {channel_name}")
    print("YouTube upload + channel-read access is ready.")


if __name__ == "__main__":
    main()
