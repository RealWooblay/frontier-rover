#!/usr/bin/env python3
"""Run and record a bounded acceptance sequence through the live heading API."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen


def request_json(url: str, path: str, body: object | None = None) -> dict[str, object]:
    data = None if body is None else json.dumps(body).encode()
    request = Request(
        f"{url.rstrip('/')}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if body is None else "POST",
    )
    with urlopen(request, timeout=2.0) as response:
        return json.loads(response.read())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://192.168.0.87:8765")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/physical/2026-09-06-heading-api-acceptance.json"),
    )
    parser.add_argument("targets", nargs="*", type=float, default=[45.0, -90.0, 45.0])
    args = parser.parse_args()

    status = request_json(args.url, "/api/status")
    telemetry = request_json(args.url, "/api/telemetry")
    if status.get("motor_active"):
        raise SystemExit("preflight failed: motors were already active")
    imu = telemetry.get("imu")
    if not isinstance(imu, dict) or imu.get("state") != "streaming":
        raise SystemExit("preflight failed: IMU is not streaming")

    records = []
    try:
        for target in args.targets:
            request_json(
                args.url,
                "/api/heading/turn",
                {"target_degrees": target},
            )
            deadline = time.monotonic() + 12.0
            while True:
                turn = request_json(args.url, "/api/heading")
                if not turn.get("active"):
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"turn {target} exceeded acceptance timeout")
                time.sleep(0.10)
            records.append(turn)
            print(json.dumps(turn), flush=True)
            if turn.get("state") != "complete":
                raise RuntimeError(f"turn {target} ended in {turn.get('state')}")
            time.sleep(0.50)
    finally:
        request_json(args.url, "/api/heading/cancel", {})

    result = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "pi_url": args.url,
        "preflight": {
            "hostname": telemetry.get("hostname"),
            "imu": imu,
            "camera_stream": telemetry.get("camera_stream"),
        },
        "turns": records,
        "summary": {
            "complete": sum(row.get("state") == "complete" for row in records),
            "requested": len(args.targets),
            "maximum_absolute_error_degrees": max(
                abs(float(row["error_degrees"])) for row in records
            ),
            "net_measured_degrees": sum(
                float(row["measured_degrees"]) for row in records
            ),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["summary"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
