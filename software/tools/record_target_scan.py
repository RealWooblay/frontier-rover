#!/usr/bin/env python3
"""Record camera pixels and repeated detector results during a measured 360 scan."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen


def request(
    base_url: str, path: str, body: object | None = None
) -> tuple[bytes, dict[str, str]]:
    data = None if body is None else json.dumps(body).encode()
    message = Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if body is None else "POST",
    )
    with urlopen(message, timeout=8.0) as response:
        return response.read(), dict(response.headers)


def request_json(
    base_url: str, path: str, body: object | None = None
) -> dict[str, object]:
    content, _headers = request(base_url, path, body)
    return json.loads(content)


def wait_for_turn(pi_url: str) -> dict[str, object]:
    deadline = time.monotonic() + 12.0
    while time.monotonic() < deadline:
        status = request_json(pi_url, "/api/heading")
        if not status.get("active"):
            if status.get("state") != "complete":
                raise RuntimeError(f"heading turn failed: {status}")
            return status
        time.sleep(0.1)
    request_json(pi_url, "/api/heading/cancel", {})
    raise TimeoutError("heading turn exceeded 12 seconds")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pi-url", default="http://192.168.0.87:8765")
    parser.add_argument("--jetson-url", default="http://192.168.55.1:8771")
    parser.add_argument("--step-degrees", type=float, default=-30.0)
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--probes", type=int, default=3)
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/physical/target-scan")
    )
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    request_json(args.jetson_url, "/api/disarm", {})
    request_json(args.jetson_url, "/api/config", {"confidence": 0.20})
    request_json(args.pi_url, "/api/action", {"forward": 0.0, "turn": 0.0})

    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        status = request_json(args.jetson_url, "/api/status")
        if status.get("detector_ready"):
            break
        time.sleep(0.25)
    else:
        raise RuntimeError("Jetson detector did not become ready")

    records: list[dict[str, object]] = []
    found = False
    try:
        for index in range(args.steps + 1):
            time.sleep(0.35)
            jpeg, headers = request(
                args.pi_url, "/api/camera/frame.jpg?after=-1"
            )
            image_name = f"sector-{index:02d}.jpg"
            (args.output / image_name).write_bytes(jpeg)

            probes = [
                request_json(args.jetson_url, "/api/probe", {})
                for _ in range(args.probes)
            ]
            detections = [probe.get("detection") for probe in probes]
            found = any(detection is not None for detection in detections)
            record = {
                "sector": index,
                "nominal_heading_degrees": index * args.step_degrees,
                "image": image_name,
                "frame_id": headers.get("X-Frame-Id"),
                "detections": detections,
                "observations": [probe.get("observation") for probe in probes],
            }
            records.append(record)
            print(json.dumps(record), flush=True)
            if found or index == args.steps:
                break
            request_json(
                args.pi_url,
                "/api/heading/turn",
                {"target_degrees": args.step_degrees},
            )
            record["turn"] = wait_for_turn(args.pi_url)
    finally:
        request_json(args.pi_url, "/api/heading/cancel", {})
        request_json(args.pi_url, "/api/action", {"forward": 0.0, "turn": 0.0})

    summary = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "found": found,
        "sectors_observed": len(records),
        "step_degrees": args.step_degrees,
        "probes_per_sector": args.probes,
        "records": records,
    }
    (args.output / "scan.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({key: value for key, value in summary.items() if key != "records"}))
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())
