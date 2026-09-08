#!/usr/bin/env python3
"""Run YOLO target perception and the shared controller against the Pi camera."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from apriltag_perception import fetch_frame
from autonomy_controller import (
    Action,
    ControlState,
    ControllerConfig,
    Observation,
    TargetController,
)
from yolo_perception import YoloDetector


def post_action(base_url: str, action: Action, timeout: float) -> float:
    body = json.dumps({"forward": action.forward, "turn": action.turn}).encode()
    request = Request(
        f"{base_url.rstrip('/')}/api/action",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise OSError(f"Pi action API returned HTTP {response.status}")
        response.read()
    return round((time.monotonic() - started) * 1000.0, 2)


def stop_action() -> Action:
    from autonomy_controller import ControlState

    return Action(0.0, 0.0, ControlState.TARGET_LOST)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pi-url", default="http://127.0.0.1:8765")
    parser.add_argument("--model", type=Path, default=Path("yolov8n.pt"))
    parser.add_argument("--target", default="bottle")
    parser.add_argument("--confidence", type=float, default=0.4)
    parser.add_argument("--target-area-ratio", type=float, default=0.143)
    parser.add_argument("--area-tolerance", type=float, default=0.007)
    parser.add_argument("--alignment-tolerance", type=float, default=0.15)
    parser.add_argument("--turn-gain", type=float, default=0.35)
    parser.add_argument("--max-forward", type=float, default=0.45)
    parser.add_argument("--max-turn", type=float, default=0.35)
    parser.add_argument("--min-turn", type=float, default=0.3)
    parser.add_argument("--search-turn", type=float, default=0.35)
    parser.add_argument("--turn-pulse-ms", type=int, default=70)
    parser.add_argument("--max-frame-age-ms", type=int, default=300)
    parser.add_argument("--device")
    parser.add_argument("--frames", type=int, default=0, help="zero runs until interrupted")
    parser.add_argument("--timeout", type=float, default=1.0)
    parser.add_argument("--send-actions", action="store_true")
    parser.add_argument("--log", type=Path)
    return parser.parse_args()


def write_record(stream, record: dict[str, object]) -> None:
    line = json.dumps(record, separators=(",", ":"))
    print(line, flush=True)
    if stream is not None:
        stream.write(line + "\n")
        stream.flush()


def run(args: argparse.Namespace) -> int:
    if args.turn_pulse_ms < 0:
        raise ValueError("turn-pulse-ms must not be negative")
    if args.model.suffix == ".engine":
        from tensorrt_yolo import TensorRTYoloDetector

        detector = TensorRTYoloDetector(
            args.model, args.target, args.confidence, args.device
        )
    else:
        detector = YoloDetector(args.model, args.target, args.confidence, args.device)
    controller_config = ControllerConfig(
        target_area_ratio=args.target_area_ratio,
        area_tolerance=args.area_tolerance,
        alignment_tolerance=args.alignment_tolerance,
        turn_gain=args.turn_gain,
        max_forward=args.max_forward,
        max_turn=args.max_turn,
        search_turn=args.search_turn,
        min_turn=args.min_turn,
        max_frame_age_ms=args.max_frame_age_ms,
    )
    controller = TargetController(controller_config)
    frame_id = -1
    processed = 0
    log_stream = None
    if args.log:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        log_stream = args.log.open("a")

    try:
        while not args.frames or processed < args.frames:
            try:
                fetched = fetch_frame(args.pi_url, frame_id, args.timeout)
                if fetched is None:
                    continue
                jpeg, frame_id, source_age_ms = fetched
                detection, perception_timing = detector.detect(jpeg)
                observation = Observation(
                    target_visible=detection is not None,
                    horizontal_error=detection.horizontal_error if detection else 0.0,
                    area_ratio=detection.area_ratio if detection else 0.0,
                    frame_age_ms=round(source_age_ms + perception_timing["total_ms"]),
                )
                action = controller.update(observation)
                command_ms = None
                pulse_stop_ms = None
                if args.send_actions:
                    command_ms = post_action(args.pi_url, action, args.timeout)
                    if (
                        action.state in (ControlState.ALIGNING, ControlState.SEARCHING)
                        and args.turn_pulse_ms > 0
                    ):
                        time.sleep(args.turn_pulse_ms / 1000.0)
                        pulse_stop_ms = post_action(
                            args.pi_url, stop_action(), args.timeout
                        )
                write_record(
                    log_stream,
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "mode": "closed_loop" if args.send_actions else "dry_run",
                        "target": args.target,
                        "confidence_threshold": args.confidence,
                        "controller_config": asdict(controller_config),
                        "frame_id": frame_id,
                        "source_age_ms": source_age_ms,
                        "perception_timing": perception_timing,
                        "command_ms": command_ms,
                        "turn_pulse_ms": args.turn_pulse_ms,
                        "pulse_stop_ms": pulse_stop_ms,
                        "detection": detection.to_dict() if detection else None,
                        "observation": asdict(observation),
                        "action": action.to_dict(),
                    },
                )
                processed += 1
            except (OSError, RuntimeError, URLError, ValueError) as error:
                write_record(
                    log_stream,
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "mode": "fault",
                        "fault": str(error),
                    },
                )
                time.sleep(0.25)
    except KeyboardInterrupt:
        return 0
    finally:
        if args.send_actions:
            try:
                post_action(args.pi_url, stop_action(), args.timeout)
            except (OSError, URLError):
                pass
        if log_stream is not None:
            log_stream.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
