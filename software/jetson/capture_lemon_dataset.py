#!/usr/bin/env python3
"""Capture canonical rover-camera frames and quality metadata for labelling."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from apriltag_perception import fetch_frame, vision_modules


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--prefix", default="lemon")
    parser.add_argument("--timeout", type=float, default=2.0)
    args = parser.parse_args()
    if args.count < 1 or args.count > 1000:
        parser.error("--count must be between 1 and 1000")
    if args.interval < 0.1:
        parser.error("--interval must be at least 0.1 seconds")
    return args


def decode_canonical(jpeg: bytes):
    cv2, numpy = vision_modules()
    raw = cv2.imdecode(numpy.frombuffer(jpeg, dtype=numpy.uint8), cv2.IMREAD_COLOR)
    if raw is None:
        raise ValueError("camera response was not a valid JPEG")
    return cv2.rotate(raw, cv2.ROTATE_90_COUNTERCLOCKWISE)


def frame_quality(frame) -> tuple[float, float]:
    cv2, _ = vision_modules()
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return round(brightness, 1), round(sharpness, 1)


def run(args: argparse.Namespace) -> int:
    cv2, _ = vision_modules()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / "manifest.jsonl"
    frame_id = -1

    with manifest_path.open("a") as manifest:
        for index in range(1, args.count + 1):
            started = time.monotonic()
            fetched = fetch_frame(args.url, frame_id, args.timeout)
            while fetched is None:
                fetched = fetch_frame(args.url, frame_id, args.timeout)
            jpeg, frame_id, source_age_ms = fetched
            frame = decode_canonical(jpeg)
            filename = f"{args.prefix}-{index:04d}.jpg"
            path = args.output / filename
            if not cv2.imwrite(str(path), frame):
                raise OSError(f"could not write {path}")
            brightness, sharpness = frame_quality(frame)
            record = {
                "filename": filename,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "frame_id": frame_id,
                "source_age_ms": source_age_ms,
                "width": int(frame.shape[1]),
                "height": int(frame.shape[0]),
                "brightness_mean": brightness,
                "laplacian_variance": sharpness,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            manifest.write(json.dumps(record) + "\n")
            manifest.flush()
            print(json.dumps(record), flush=True)
            remaining = args.interval - (time.monotonic() - started)
            if remaining > 0 and index < args.count:
                time.sleep(remaining)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
