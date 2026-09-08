#!/usr/bin/env python3
"""Observe an AprilTag and print safe controller decisions without moving."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import time
from urllib.error import URLError

from apriltag_perception import detect_frame, fetch_frame
from autonomy_controller import Observation, TargetController


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--tag-id", type=int, default=0)
    parser.add_argument("--frames", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=2.0)
    return parser.parse_args()


def run(args: argparse.Namespace) -> int:
    controller = TargetController()
    frame_id = -1
    processed = 0

    while processed < args.frames:
        try:
            fetched = fetch_frame(args.url, frame_id, args.timeout)
            if fetched is None:
                continue
            jpeg, frame_id, frame_age_ms = fetched
            _, measurements = detect_frame(jpeg, args.tag_id)
            primary = measurements[0] if measurements else None
            observation = Observation(
                target_visible=primary is not None,
                horizontal_error=primary.horizontal_error if primary else 0.0,
                area_ratio=primary.area_ratio if primary else 0.0,
                frame_age_ms=frame_age_ms,
            )
            action = controller.update(observation)
            print(
                json.dumps(
                    {
                        "frame_id": frame_id,
                        "observation": asdict(observation),
                        "action": action.to_dict(),
                    }
                ),
                flush=True,
            )
            processed += 1
        except (OSError, URLError, ValueError) as error:
            print(json.dumps({"fault": str(error)}), flush=True)
            time.sleep(0.25)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
