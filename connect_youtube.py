#!/usr/bin/env python3
import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_FILE = Path("client_secret.json")
TOKEN_FILE = Path("youtube_token.json")


def main():
    if not CLIENT_FILE.exists():
        raise SystemExit("Missing client_secret.json. Download an OAuth Desktop client JSON from Google Cloud first.")

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    print(f"Saved {TOKEN_FILE}. Copy its full JSON into GitHub secret YOUTUBE_TOKEN_JSON.")


if __name__ == "__main__":
    main()
