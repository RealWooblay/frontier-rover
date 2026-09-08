#!/usr/bin/env python3
"""Report deterministic orange detections for canonical rover camera images."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy

from tensorrt_yolo import detect_orange_color


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path)
    args = parser.parse_args()

    for path in args.images:
        raw = cv2.imread(str(path))
        if raw is None:
            raise ValueError(f"could not read {path}")
        frame = cv2.rotate(raw, cv2.ROTATE_90_COUNTERCLOCKWISE)
        detection = detect_orange_color(frame, cv2, numpy)
        print(
            json.dumps(
                {
                    "image": str(path),
                    "detection": detection.to_dict() if detection else None,
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
