#!/usr/bin/env python3
"""Measure HTTP camera delivery without importing or sending motor commands."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.request import urlopen


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower), 3)


def benchmark(base_url, seconds):
    if not 1 <= seconds <= 120:
        raise ValueError("duration must be between 1 and 120 seconds")
    start = time.monotonic()
    rows, errors = [], []
    previous_id, previous_time = -1, None
    while time.monotonic() - start < seconds:
        request_start = time.monotonic()
        try:
            with urlopen(f"{base_url.rstrip('/')}/api/camera/frame.jpg?after={previous_id}", timeout=2) as response:
                if response.status == 200:
                    jpeg = response.read()
                    now = time.monotonic()
                    frame_id = int(response.headers["X-Frame-Id"])
                    if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
                        raise ValueError("invalid JPEG boundary")
                    rows.append({
                        "elapsed_s": round(now - start, 4), "frame_id": frame_id,
                        "published_age_ms": int(response.headers["X-Frame-Age-Ms"]),
                        "http_ms": round((now - request_start) * 1000, 3),
                        "gap_ms": None if previous_time is None else round((now - previous_time) * 1000, 3),
                        "skipped_ids": max(0, frame_id - previous_id - 1) if previous_id >= 0 else 0,
                        "bytes": len(jpeg),
                    })
                    previous_id, previous_time = frame_id, now
                elif response.status != 204:
                    raise ValueError(f"unexpected HTTP status {response.status}")
        except (OSError, ValueError, TypeError) as error:
            errors.append({"elapsed_s": round(time.monotonic() - start, 4), "error": str(error)})
            time.sleep(0.25)
        time.sleep(0.02)
    duration = time.monotonic() - start
    gaps = [row["gap_ms"] for row in rows if row["gap_ms"] is not None]
    ages = [row["published_age_ms"] for row in rows]
    return {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url, "duration_s": round(duration, 3),
        "motion_commands_sent": 0,
        "summary": {
            "unique_frames": len(rows), "delivered_fps": round(len(rows) / duration, 2),
            "gap_p50_ms": percentile(gaps, 0.5), "gap_p95_ms": percentile(gaps, 0.95),
            "max_gap_ms": max(gaps, default=None),
            "published_age_p50_ms": percentile(ages, 0.5),
            "published_age_p95_ms": percentile(ages, 0.95),
            "skipped_frame_ids": sum(row["skipped_ids"] for row in rows),
            "errors": len(errors),
        },
        "limits": "Measures delivery to this collector. Header age starts at Pi publication, not sensor exposure. This is not end-to-end optical latency.",
        "frames": rows, "errors": errors,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pi-url", default="http://192.168.0.87:8765")
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; preserve it and choose a new filename")
    result = benchmark(args.pi_url, args.seconds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"output": str(args.output), "summary": result["summary"]}, indent=2))
    return 0 if result["summary"]["unique_frames"] and not result["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
