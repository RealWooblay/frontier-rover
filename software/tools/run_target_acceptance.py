#!/usr/bin/env python3
"""Run one bounded Jetson target mission and retain every observed transition."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen


def request_json(url: str, path: str, body: object | None = None) -> dict[str, object]:
    request = Request(
        f"{url.rstrip('/')}{path}",
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="GET" if body is None else "POST",
    )
    with urlopen(request, timeout=3.0) as response:
        return json.loads(response.read())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://192.168.55.1:8771")
    parser.add_argument("--target", default="orange")
    parser.add_argument("--seconds", type=float, default=25.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/physical/2026-09-06-jetson-service-mission.json"),
    )
    args = parser.parse_args()

    request_json(args.url, "/api/disarm", {})
    request_json(
        args.url,
        "/api/config",
        {
            "target": args.target,
            "confidence": 0.20,
            "target_area_ratio": 0.110,
            "arrival_bottom_ratio": 0.920,
            "arrival_min_area_ratio": 0.030,
            "close_loss_area_ratio": 0.090,
            "minimum_target_area_ratio": 0.005,
            "alignment_tolerance": 0.40,
            "turn_gain": 0.12,
            "max_forward": 0.70,
            "max_turn": 0.35,
            "search_turn": 0.35,
            "turn_pulse_ms": 45,
            "alignment_pulse_ms": 35,
            "reacquire_hold_ms": 1500,
            "max_frame_age_ms": 500,
            "approach_pulse_ms": 150,
            "maximum_search_steps": 46,
            "recovery_reverse": 0.35,
            "recovery_reverse_ms": 300,
            "maximum_search_cycles": 3,
        },
    )
    deadline = time.monotonic() + args.seconds
    samples = []
    outcome = "timeout"
    try:
        request_json(args.url, "/api/arm", {})
        while time.monotonic() < deadline:
            status = request_json(args.url, "/api/status")
            samples.append(
                {
                    "elapsed_s": round(args.seconds - (deadline - time.monotonic()), 3),
                    "state": status.get("state"),
                    "armed": status.get("armed"),
                    "frame_id": status.get("frame_id"),
                    "detection": status.get("detection"),
                    "observation": status.get("observation"),
                    "action": status.get("action"),
                    "perception_timing": status.get("perception_timing"),
                    "command_ms": status.get("command_ms"),
                    "pulse_stop_ms": status.get("pulse_stop_ms"),
                    "fault": status.get("fault"),
                }
            )
            state = status.get("state")
            if state == "arrived":
                outcome = "arrived"
                break
            if state == "fault" or not status.get("armed"):
                outcome = "fault"
                break
            time.sleep(0.10)
    finally:
        final = request_json(args.url, "/api/disarm", {})

    states = Counter(str(sample["state"]) for sample in samples)
    result = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "service_url": args.url,
        "target": args.target,
        "time_limit_s": args.seconds,
        "outcome": outcome,
        "state_counts": dict(states),
        "frames_observed": len({sample["frame_id"] for sample in samples}),
        "service_mission_state_counts": final.get("mission_state_counts"),
        "maximum_area_ratio": max(
            (
                float(sample["observation"]["area_ratio"])
                for sample in samples
                if isinstance(sample["observation"], dict)
            ),
            default=0.0,
        ),
        "maximum_absolute_horizontal_error": max(
            (
                abs(float(sample["observation"]["horizontal_error"]))
                for sample in samples
                if isinstance(sample["observation"], dict)
            ),
            default=0.0,
        ),
        "final": final,
        "samples": samples,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "samples"}, indent=2))
    return 0 if outcome == "arrived" else 1


if __name__ == "__main__":
    raise SystemExit(main())
