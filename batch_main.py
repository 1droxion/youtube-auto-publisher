#!/usr/bin/env python3
import argparse
import os

from pro_batch import process_batch


def main():
    parser = argparse.ArgumentParser(description="Create one professionally edited YouTube video from 2-20 rights-cleared clips.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--urls", help="Source URLs separated by newlines, commas, semicolons, or |.")
    group.add_argument("--urls-env", help="Read the source URL list from this environment variable.")
    parser.add_argument("--rights-ok", action="store_true", help="Confirm you own or have permission/license to reuse every source clip.")
    parser.add_argument("--music-policy", choices=["stop", "mute", "ignore"], default="stop")
    parser.add_argument("--privacy", choices=["private", "unlisted", "public"], default="private")
    parser.add_argument("--broll-count", type=int, choices=[0, 1, 2, 3], default=2)
    parser.add_argument("--no-upload", action="store_true")
    args = parser.parse_args()

    raw_urls = args.urls if args.urls is not None else os.getenv(args.urls_env, "")
    process_batch(
        raw_urls=raw_urls,
        rights_ok=args.rights_ok,
        music_policy=args.music_policy,
        privacy=args.privacy,
        upload=not args.no_upload,
        broll_count=args.broll_count,
    )


if __name__ == "__main__":
    main()
