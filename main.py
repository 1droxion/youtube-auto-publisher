#!/usr/bin/env python3
import argparse

from pipeline import process


def main():
    parser = argparse.ArgumentParser(description="Download, clean, package, and optionally upload a rights-cleared YouTube video.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--rights-ok", action="store_true", help="Confirm you own or have permission/license to reuse this video.")
    parser.add_argument("--music-policy", choices=["stop", "mute", "ignore"], default="stop")
    parser.add_argument("--privacy", choices=["private", "unlisted", "public"], default="private")
    parser.add_argument("--no-upload", action="store_true")
    args = parser.parse_args()

    process(
        url=args.url,
        rights_ok=args.rights_ok,
        music_policy=args.music_policy,
        privacy=args.privacy,
        upload=not args.no_upload,
    )


if __name__ == "__main__":
    main()
