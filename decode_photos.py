#!/usr/bin/env python3
"""Restore the Viavios story photos from their base64 text copies.

The JPEGs in static/img/ travel through the GitHub push pipeline as plain
base64 text files in static/img_b64/ (the pipeline carries UTF-8 text only).
Run this once after cloning (Render runs it automatically at build time):

    python3 decode_photos.py

Stdlib only. Idempotent: a photo that already exists with identical bytes
is skipped.
"""
import base64
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
B64_DIR = ROOT / "static" / "img_b64"
IMG_DIR = ROOT / "static" / "img"


def main() -> int:
    if not B64_DIR.is_dir():
        print(f"No base64 photo directory found at {B64_DIR} — nothing to do.")
        return 0
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    restored, skipped = 0, 0
    for b64_file in sorted(B64_DIR.glob("*.jpg.b64")):
        name = b64_file.name[: -len(".b64")]
        target = IMG_DIR / name
        data = base64.b64decode(b64_file.read_text().encode("ascii"))
        if target.exists() and target.read_bytes() == data:
            skipped += 1
            continue
        target.write_bytes(data)
        restored += 1
        print(f"restored {name} ({len(data)} bytes)")
    print(f"decode_photos: {restored} restored, {skipped} already up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
