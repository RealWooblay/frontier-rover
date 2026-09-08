#!/usr/bin/env python3
"""Fit MuJoCo actuator gain and velocity feedback to physical IMU data."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import statistics

from mujoco_rover import DynamicsParameters, RoverSimulation


GYRO_AXES = ("gx_dps", "gy_dps", "gz_dps")
TURN_PHASES = ("turn_left", "turn_right")
STOP_PHASES = {
    "turn_left": "stationary_after_left",
    "turn_right": "stationary_after_right",
}


def rows_for(rows: list[dict[str, str]], phase: str) -> list[dict[str, str]]:
    return [row for row in rows if row["phase"] == phase]


def stationary_bias(rows: list[dict[str, str]]) -> tuple[float, float, float]:
    stationary = rows_for(rows, "stationary_before")
    if not stationary:
        raise ValueError("log has no stationary_before samples")
    return tuple(
        statistics.fmean(float(row[axis]) for row in stationary)
        for axis in GYRO_AXES
    )


def identify_yaw_axis(
    rows: list[dict[str, str]], bias: tuple[float, float, float]
) -> int:
    scores = []
    for index, axis in enumerate(GYRO_AXES):
        phase_means = []
        for phase in TURN_PHASES:
            phase_rows = rows_for(rows, phase)
            if not phase_rows:
                raise ValueError(f"log has no {phase} samples")
            phase_means.append(
                abs(
                    statistics.fmean(float(row[axis]) for row in phase_rows)
                    - bias[index]
                )
            )
        scores.append(statistics.fmean(phase_means))
    return max(range(len(scores)), key=scores.__getitem__)


def integrate_angle_degrees(
    rows: list[dict[str, str]], axis: str, bias: float
) -> float:
    total = 0.0
    for previous, current in zip(rows, rows[1:]):
        dt = float(current["time_s"]) - float(previous["time_s"])
        previous_rate = float(previous[axis]) - bias
        current_rate = float(current[axis]) - bias
        total += (previous_rate + current_rate) * 0.5 * dt
    return total


def phase_input(rows: list[dict[str, str]]) -> tuple[float, float, float]:
    if len(rows) < 2:
        raise ValueError("motion phase requires at least two samples")
    # The first HTTP response can precede the 10 ms motor-loop tick and still
    # report the previous stopped output. The median represents the steady
    # command for this constant-input phase without treating that transition
    # observation as lower PWM.
    left = statistics.median(float(row["left_pwm"]) for row in rows)
    right = statistics.median(float(row["right_pwm"]) for row in rows)
    intervals = [
        float(current["time_s"]) - float(previous["time_s"])
        for previous, current in zip(rows, rows[1:])
    ]
    duration = float(rows[-1]["time_s"]) - float(rows[0]["time_s"])
    duration += statistics.median(intervals)
    forward = (left + right) * 0.5
    turn = (left - right) * 0.5
    return forward, turn, duration


def integrated_trace(
    rows: list[dict[str, str]], axis: str, bias: float
) -> list[float]:
    trace = [0.0]
    for previous, current in zip(rows, rows[1:]):
        dt = float(current["time_s"]) - float(previous["time_s"])
        previous_rate = float(previous[axis]) - bias
        current_rate = float(current[axis]) - bias
        trace.append(trace[-1] + (previous_rate + current_rate) * 0.5 * dt)
    return trace


def simulated_trace(
    rows: list[dict[str, str]],
    turn_phase: str,
    turn_input: float,
    parameters: DynamicsParameters,
) -> list[float]:
    simulation = RoverSimulation(parameters=parameters)
    trace = [0.0]
    previous_heading = 0.0
    unwrapped_heading = 0.0
    for previous, current in zip(rows, rows[1:]):
        dt = float(current["time_s"]) - float(previous["time_s"])
        turn = turn_input if previous["phase"] == turn_phase else 0.0
        heading = simulation.step(0.0, turn, dt).heading_rad
        change = (heading - previous_heading + math.pi) % (2 * math.pi) - math.pi
        unwrapped_heading += change
        previous_heading = heading
        trace.append(math.degrees(unwrapped_heading))
    return trace


def segment_rows(rows: list[dict[str, str]], turn_phase: str):
    phases = (turn_phase, STOP_PHASES[turn_phase])
    return [row for row in rows if row["phase"] in phases]


def trajectory_error(
    rows: list[dict[str, str]],
    observed: list[float],
    turn_phase: str,
    turn_input: float,
    parameters: DynamicsParameters,
) -> tuple[float, list[float]]:
    predicted = simulated_trace(rows, turn_phase, turn_input, parameters)
    squared_error = sum(
        (prediction - measurement) ** 2
        for prediction, measurement in zip(predicted, observed)
    )
    return squared_error, predicted


def fit_actuator(
    segments: dict[str, list[dict[str, str]]],
    observed: dict[str, list[float]],
    inputs: dict[str, tuple[float, float, float]],
) -> tuple[DynamicsParameters, dict[str, list[float]], float]:
    best: tuple[float, DynamicsParameters, dict[str, list[float]]] | None = None
    for velocity_step in range(1, 21):
        velocity_feedback = velocity_step / 1000.0
        direction_fits: dict[str, tuple[float, float, list[float]]] = {}
        for phase in TURN_PHASES:
            phase_best: tuple[float, float, list[float]] | None = None
            for gain_step in range(30, 151, 2):
                gain = gain_step / 100.0
                parameters = DynamicsParameters(
                    floor_friction=1.0,
                    left_turn_gain=gain if phase == "turn_left" else 0.87,
                    right_turn_gain=gain if phase == "turn_right" else 0.87,
                    velocity_feedback=velocity_feedback,
                )
                error, predicted = trajectory_error(
                    segments[phase],
                    observed[phase],
                    phase,
                    inputs[phase][1],
                    parameters,
                )
                candidate = (error, gain, predicted)
                if phase_best is None or candidate[0] < phase_best[0]:
                    phase_best = candidate
            assert phase_best is not None
            direction_fits[phase] = phase_best

        total_error = sum(result[0] for result in direction_fits.values())
        parameters = DynamicsParameters(
            floor_friction=1.0,
            left_turn_gain=direction_fits["turn_left"][1],
            right_turn_gain=direction_fits["turn_right"][1],
            velocity_feedback=velocity_feedback,
        )
        predicted = {
            phase: direction_fits[phase][2] for phase in TURN_PHASES
        }
        candidate = (total_error, parameters, predicted)
        if best is None or candidate[0] < best[0]:
            best = candidate

    assert best is not None
    sample_count = sum(len(values) for values in observed.values())
    return best[1], best[2], math.sqrt(best[0] / sample_count)


def analyze(path: Path) -> dict[str, object]:
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    bias = stationary_bias(rows)
    yaw_index = identify_yaw_axis(rows, bias)
    yaw_axis = GYRO_AXES[yaw_index]
    inputs = {phase: phase_input(rows_for(rows, phase)) for phase in TURN_PHASES}
    segments = {phase: segment_rows(rows, phase) for phase in TURN_PHASES}
    observed = {
        phase: integrated_trace(segments[phase], yaw_axis, bias[yaw_index])
        for phase in TURN_PHASES
    }
    parameters, predicted, rmse = fit_actuator(segments, observed, inputs)
    return {
        "source": str(path),
        "sample_count": len(rows),
        "gyro_bias_dps": dict(zip(GYRO_AXES, bias)),
        "yaw_axis": yaw_axis,
        "observed_final_degrees": {
            phase: trace[-1] for phase, trace in observed.items()
        },
        "input": {
            phase: {"forward": values[0], "turn": values[1], "duration_s": values[2]}
            for phase, values in inputs.items()
        },
        "fit": {
            "left_turn_gain": parameters.left_turn_gain,
            "right_turn_gain": parameters.right_turn_gain,
            "velocity_feedback": parameters.velocity_feedback,
            "simulated_final_degrees": {
                phase: trace[-1] for phase, trace in predicted.items()
            },
            "trajectory_rmse_degrees": rmse,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = analyze(args.input)
    encoded = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
