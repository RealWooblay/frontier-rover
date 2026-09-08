#!/usr/bin/env python3
"""Measure AprilTag position in the Raspberry Pi rover camera stream."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time
from typing import Sequence
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen


@dataclass(frozen=True)
class TagMeasurement:
    tag_id: int
    center_x_px: float
    center_y_px: float
    horizontal_error: float
    area_ratio: float


def polygon_area(points: Sequence[Sequence[float]]) -> float:
    area = 0.0
    for index, point in enumerate(points):
        next_point = points[(index + 1) % len(points)]
        area += point[0] * next_point[1] - next_point[0] * point[1]
    return abs(area) / 2.0


def measure_tag(
    tag_id: int,
    corners: Sequence[Sequence[float]],
    frame_width: int,
    frame_height: int,
) -> TagMeasurement:
    if len(corners) != 4 or frame_width <= 0 or frame_height <= 0:
        raise ValueError("a tag needs four corners and a non-empty frame")
    center_x = sum(point[0] for point in corners) / 4.0
    center_y = sum(point[1] for point in corners) / 4.0
    horizontal_error = (center_x - frame_width / 2.0) / (frame_width / 2.0)
    return TagMeasurement(
        tag_id=tag_id,
        center_x_px=round(center_x, 2),
        center_y_px=round(center_y, 2),
        horizontal_error=round(max(-1.0, min(1.0, horizontal_error)), 4),
        area_ratio=round(polygon_area(corners) / (frame_width * frame_height), 6),
    )


def vision_modules():
    try:
        import cv2  # type: ignore
        import numpy  # type: ignore
    except ImportError as error:
        raise SystemExit("OpenCV and NumPy are required on the Jetson") from error
    if not hasattr(cv2, "aruco") or not hasattr(cv2.aruco, "DICT_APRILTAG_36h11"):
        raise SystemExit("This OpenCV build lacks AprilTag 36h11 support")
    return cv2, numpy


def april_tag_dictionary(cv2):
    return cv2.aruco.Dictionary_get(cv2.aruco.DICT_APRILTAG_36h11)


def generate_tag(path: Path, tag_id: int, size: int) -> None:
    cv2, numpy = vision_modules()
    marker_size = int(size * 0.8)
    marker = cv2.aruco.drawMarker(april_tag_dictionary(cv2), tag_id, marker_size)
    image = numpy.full((size, size), 255, dtype=numpy.uint8)
    offset = (size - marker_size) // 2
    image[offset : offset + marker_size, offset : offset + marker_size] = marker
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), image):
        raise SystemExit(f"could not write {path}")


def fetch_frame(base_url: str, after: int, timeout: float):
    query = urlencode({"after": after})
    with urlopen(f"{base_url.rstrip('/')}/api/camera/frame.jpg?{query}", timeout=timeout) as response:
        if response.status == 204:
            return None
        return (
            response.read(),
            int(response.headers.get("X-Frame-Id", after + 1)),
            int(response.headers.get("X-Frame-Age-Ms", 0)),
        )


def detect_frame(jpeg: bytes, tag_id: int | None):
    cv2, numpy = vision_modules()
    raw = cv2.imdecode(numpy.frombuffer(jpeg, dtype=numpy.uint8), cv2.IMREAD_COLOR)
    if raw is None:
        raise ValueError("camera response was not a valid JPEG")

    frame = cv2.rotate(raw, cv2.ROTATE_90_COUNTERCLOCKWISE)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    parameters = cv2.aruco.DetectorParameters_create()
    corners, ids, _ = cv2.aruco.detectMarkers(
        gray,
        april_tag_dictionary(cv2),
        parameters=parameters,
    )
    measurements: list[TagMeasurement] = []
    if ids is not None:
        cv2.aruco.drawDetectedMarkers(frame, corners, ids)
        for detected_corners, detected_id in zip(corners, ids.flatten()):
            detected_id = int(detected_id)
            if tag_id is not None and detected_id != tag_id:
                continue
            points = detected_corners.reshape(4, 2).tolist()
            measurements.append(
                measure_tag(detected_id, points, frame.shape[1], frame.shape[0])
            )
    measurements.sort(key=lambda item: item.area_ratio, reverse=True)
    return frame, measurements


def run(args: argparse.Namespace) -> int:
    if args.generate_tag:
        generate_tag(args.generate_tag, args.tag_id, args.tag_size)
        print(json.dumps({"generated": str(args.generate_tag), "tag_id": args.tag_id}))
        return 0

    frame_id = -1
    processed_frames = 0
    while True:
        started = time.monotonic()
        try:
            fetched = fetch_frame(args.url, frame_id, args.timeout)
            if fetched is None:
                continue
            jpeg, frame_id, source_age_ms = fetched
            frame, measurements = detect_frame(jpeg, args.tag_id)
            if args.output:
                cv2, _ = vision_modules()
                cv2.imwrite(str(args.output), frame)
            result = {
                "frame_id": frame_id,
                "source_age_ms": source_age_ms,
                "processing_ms": round((time.monotonic() - started) * 1000, 1),
                "detected": bool(measurements),
                "primary": asdict(measurements[0]) if measurements else None,
                "detections": [asdict(item) for item in measurements],
            }
            print(json.dumps(result), flush=True)
            processed_frames += 1
        except (OSError, URLError, ValueError) as error:
            print(json.dumps({"fault": str(error)}), flush=True)
            time.sleep(0.25)
        if args.once or (args.frames and processed_frames >= args.frames):
            return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--tag-id", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--frames", type=int, default=0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--generate-tag", type=Path)
    parser.add_argument("--tag-size", type=int, default=1000)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
