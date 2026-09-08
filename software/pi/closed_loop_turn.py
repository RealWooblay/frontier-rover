#!/usr/bin/env python3
"""Execute bounded relative turns using MPU-9250 yaw feedback."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
import statistics
import time

from imu import LinuxI2C, MPU9250
from imu_motion_experiment import MotorClient


SAMPLE_HZ = 50.0
COMMAND_HZ = 10.0
TURN_THROTTLE = 0.7
STOP_EARLY_DEGREES = 12.0
TOLERANCE_DEGREES = 4.0
SETTLE_SECONDS = 0.25
MAX_CORRECTIONS = 8


@dataclass(frozen=True)
class TurnResult:
    target_degrees: float
    measured_degrees: float
    error_degrees: float
    corrections: int
    elapsed_seconds: float


class YawIntegrator:
    def __init__(self, bias_dps: float) -> None:
        self.bias_dps = bias_dps
        self.angle_degrees = 0.0
        self.previous_time_ns: int | None = None
        self.previous_rate_dps: float | None = None

    def update(self, timestamp_ns: int, raw_rate_dps: float) -> float:
        rate_dps = raw_rate_dps - self.bias_dps
        if self.previous_time_ns is not None and self.previous_rate_dps is not None:
            dt = (timestamp_ns - self.previous_time_ns) / 1e9
            self.angle_degrees += (self.previous_rate_dps + rate_dps) * 0.5 * dt
        self.previous_time_ns = timestamp_ns
        self.previous_rate_dps = rate_dps
        return rate_dps


def direction_for(error_degrees: float) -> str:
    return "left" if error_degrees > 0 else "right"


def correction_duration(error_degrees: float) -> float:
    return min(0.15, max(0.05, abs(error_degrees) / 160.0))


def calibrate_yaw_bias(
    imu: MPU9250,
    motors: MotorClient,
    *,
    duration_s: float = 1.5,
) -> tuple[float, float]:
    motors.command("stop", 0.0)
    rates = []
    deadline = time.monotonic() + duration_s
    interval = 1.0 / SAMPLE_HZ
    next_sample = time.monotonic()
    while time.monotonic() < deadline:
        sample = imu.sample()
        rates.append(sample.gyro_dps[1])
        next_sample += interval
        time.sleep(max(0.0, next_sample - time.monotonic()))
    noise = statistics.pstdev(rates)
    if noise > 2.0:
        raise RuntimeError(
            f"rover was not stationary during gyro calibration: noise={noise:.2f} dps"
        )
    return statistics.fmean(rates), noise


def execute_turn(
    target_degrees: float,
    imu: MPU9250,
    motors: MotorClient,
    writer: csv.writer,
    *,
    bias_dps: float,
    turn_number: int,
) -> TurnResult:
    if not -180.0 <= target_degrees <= 180.0 or target_degrees == 0.0:
        raise ValueError("target angle must be nonzero and within -180 to 180 degrees")

    integrator = YawIntegrator(bias_dps)
    start = time.monotonic()
    timeout_s = max(4.0, abs(target_degrees) / 30.0 + 3.0)
    state = "drive"
    corrections = 0
    state_deadline = 0.0
    next_command = start
    next_sample = start
    motion = direction_for(target_degrees)
    throttle = TURN_THROTTLE

    while time.monotonic() - start < timeout_s:
        now = time.monotonic()
        sample = imu.sample()
        corrected_rate = integrator.update(sample.timestamp_ns, sample.gyro_dps[1])
        error = target_degrees - integrator.angle_degrees

        if state == "drive" and (
            abs(error) <= STOP_EARLY_DEGREES
            or error * target_degrees <= 0.0
        ):
            motors.command("stop", 0.0)
            state = "settle"
            state_deadline = now + SETTLE_SECONDS
            motion = "stop"
            throttle = 0.0
        elif state == "settle" and now >= state_deadline:
            if abs(error) <= TOLERANCE_DEGREES:
                return TurnResult(
                    target_degrees,
                    integrator.angle_degrees,
                    error,
                    corrections,
                    now - start,
                )
            corrections += 1
            if corrections > MAX_CORRECTIONS:
                raise RuntimeError(
                    f"turn failed to converge: target={target_degrees:.1f}, "
                    f"measured={integrator.angle_degrees:.1f}"
                )
            motion = direction_for(error)
            throttle = TURN_THROTTLE
            motors.command(motion, throttle)
            state = "correct"
            state_deadline = now + correction_duration(error)
            next_command = now + 1.0 / COMMAND_HZ
        elif state == "correct" and now >= state_deadline:
            motors.command("stop", 0.0)
            state = "settle"
            state_deadline = now + SETTLE_SECONDS
            motion = "stop"
            throttle = 0.0
        elif state in ("drive", "correct") and now >= next_command:
            motors.command(motion, throttle)
            next_command += 1.0 / COMMAND_HZ

        ax, ay, az = sample.accel_g
        gx, gy, gz = sample.gyro_dps
        writer.writerow(
            (
                f"{now - start:.6f}",
                turn_number,
                state,
                f"{target_degrees:.3f}",
                f"{integrator.angle_degrees:.6f}",
                f"{error:.6f}",
                motion,
                f"{throttle:.3f}",
                f"{corrected_rate:.6f}",
                f"{ax:.6f}",
                f"{ay:.6f}",
                f"{az:.6f}",
                f"{gx:.6f}",
                f"{gy:.6f}",
                f"{gz:.6f}",
            )
        )
        next_sample += 1.0 / SAMPLE_HZ
        time.sleep(max(0.0, next_sample - time.monotonic()))

    raise TimeoutError(
        f"turn timed out: target={target_degrees:.1f}, "
        f"measured={integrator.angle_degrees:.1f}"
    )


def run_sequence(
    angles: list[float], output: Path, imu: MPU9250, motors: MotorClient
) -> list[TurnResult]:
    output.parent.mkdir(parents=True, exist_ok=True)
    imu.configure()
    bias, noise = calibrate_yaw_bias(imu, motors)
    print(f"yaw calibration: bias={bias:.3f} dps, noise={noise:.3f} dps")
    results = []
    try:
        with output.open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(
                (
                    "turn_time_s",
                    "turn_number",
                    "state",
                    "target_degrees",
                    "measured_degrees",
                    "error_degrees",
                    "motion",
                    "throttle",
                    "yaw_rate_dps",
                    "ax_g",
                    "ay_g",
                    "az_g",
                    "gx_dps",
                    "gy_dps",
                    "gz_dps",
                )
            )
            for turn_number, angle in enumerate(angles, start=1):
                result = execute_turn(
                    angle,
                    imu,
                    motors,
                    writer,
                    bias_dps=bias,
                    turn_number=turn_number,
                )
                results.append(result)
                motors.command("stop", 0.0)
                print(
                    f"turn {turn_number}: target={angle:+.1f}, "
                    f"measured={result.measured_degrees:+.1f}, "
                    f"error={result.error_degrees:+.1f}, "
                    f"corrections={result.corrections}"
                )
                time.sleep(0.5)
    finally:
        motors.command("stop", 0.0)
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("angles", type=float, nargs="+")
    parser.add_argument("--controller", default="http://127.0.0.1:8765")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    imu = MPU9250(LinuxI2C("/dev/i2c-1", 0x68))
    try:
        results = run_sequence(args.angles, args.output, imu, MotorClient(args.controller))
    finally:
        imu.close()
    if any(abs(result.error_degrees) > TOLERANCE_DEGREES for result in results):
        return 1
    print(f"saved {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
