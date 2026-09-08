#!/usr/bin/env python3
"""Record synchronized MPU measurements during a bounded rover motion sequence."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
from pathlib import Path
import time
from urllib import request

from imu import LinuxI2C, MPU9250


@dataclass(frozen=True)
class Phase:
    name: str
    motion: str
    throttle: float
    duration_s: float


PHASES = (
    Phase("stationary_before", "stop", 0.0, 2.0),
    Phase("forward", "forward", 0.8, 1.2),
    Phase("stationary_after_forward", "stop", 0.0, 1.0),
    Phase("reverse", "reverse", 0.8, 1.2),
    Phase("stationary_after_reverse", "stop", 0.0, 1.0),
    Phase("turn_left", "left", 0.7, 0.6),
    Phase("stationary_after_left", "stop", 0.0, 1.0),
    Phase("turn_right", "right", 0.7, 0.6),
    Phase("stationary_after_right", "stop", 0.0, 2.0),
)


class MotorClient:
    def __init__(self, base_url: str) -> None:
        self.command_url = base_url.rstrip("/") + "/api/command"

    def command(self, motion: str, throttle: float) -> dict[str, object]:
        body = json.dumps({"motion": motion, "throttle": throttle}).encode()
        message = request.Request(
            self.command_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(message, timeout=0.25) as response:
            payload = json.load(response)
        if not isinstance(payload, dict):
            raise RuntimeError("motor API returned a non-object response")
        return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--controller", default="http://127.0.0.1:8765")
    parser.add_argument("--i2c-device", default="/dev/i2c-1")
    parser.add_argument("--i2c-address", type=lambda value: int(value, 0), default=0x68)
    return parser.parse_args()


def run_experiment(
    output: Path,
    imu: MPU9250,
    motors: MotorClient,
    *,
    sample_hz: float = 50.0,
    command_hz: float = 10.0,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    imu.configure()
    experiment_start_ns = time.monotonic_ns()
    sample_interval = 1.0 / sample_hz
    command_interval = 1.0 / command_hz

    with output.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            (
                "time_s",
                "phase",
                "requested_motion",
                "throttle",
                "left_pwm",
                "right_pwm",
                "ax_g",
                "ay_g",
                "az_g",
                "gx_dps",
                "gy_dps",
                "gz_dps",
                "temperature_c",
            )
        )

        try:
            for phase in PHASES:
                print(f"{phase.name}: {phase.motion} for {phase.duration_s:.1f}s")
                phase_start = time.monotonic()
                next_sample = phase_start
                next_command = phase_start
                left_pwm = 0.0
                right_pwm = 0.0

                while time.monotonic() - phase_start < phase.duration_s:
                    now = time.monotonic()
                    if now >= next_command:
                        status = motors.command(phase.motion, phase.throttle)
                        left_pwm = float(status.get("left_output", 0.0))
                        right_pwm = float(status.get("right_output", 0.0))
                        next_command += command_interval
                    if now >= next_sample:
                        sample = imu.sample()
                        ax, ay, az = sample.accel_g
                        gx, gy, gz = sample.gyro_dps
                        writer.writerow(
                            (
                                f"{(sample.timestamp_ns - experiment_start_ns) / 1e9:.6f}",
                                phase.name,
                                phase.motion,
                                f"{phase.throttle:.3f}",
                                f"{left_pwm:.3f}",
                                f"{right_pwm:.3f}",
                                f"{ax:.6f}",
                                f"{ay:.6f}",
                                f"{az:.6f}",
                                f"{gx:.6f}",
                                f"{gy:.6f}",
                                f"{gz:.6f}",
                                f"{sample.temperature_c:.3f}",
                            )
                        )
                        next_sample += sample_interval
                    time.sleep(max(0.0, min(next_sample, next_command) - time.monotonic()))
        finally:
            motors.command("stop", 0.0)


def main() -> int:
    args = parse_args()
    imu = MPU9250(LinuxI2C(args.i2c_device, args.i2c_address))
    try:
        run_experiment(args.output, imu, MotorClient(args.controller))
    finally:
        imu.close()
    print(f"saved {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
