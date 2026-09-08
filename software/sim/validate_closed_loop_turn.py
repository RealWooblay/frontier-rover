#!/usr/bin/env python3
"""Replay a held-out physical command log through old and fitted MuJoCo models."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics

import mujoco

from mujoco_rover import RoverSimulation, action_to_tank


TURN_PWM = 0.50


def command_turn(row: dict[str, str]) -> float:
    throttle = float(row["throttle"])
    return {
        "left": -TURN_PWM * throttle,
        "right": TURN_PWM * throttle,
        "stop": 0.0,
    }[row["motion"]]


def angle_change(current: float, previous: float) -> float:
    return (current - previous + math.pi) % (2 * math.pi) - math.pi


def configure_legacy_model(simulation: RoverSimulation) -> None:
    """Reproduce the direct constant-torque model used before velocity feedback."""
    model = simulation.model
    model.actuator_gear[:, 0] = 3.03
    model.actuator_gainprm[:, 0] = 1.0
    model.actuator_biasprm[:] = 0.0
    model.actuator_biastype[:] = mujoco.mjtBias.mjBIAS_NONE
    model.actuator_forcerange[:] = (-0.08, 0.08)


def replay(rows: list[dict[str, str]], *, legacy: bool) -> float:
    simulation = RoverSimulation()
    if legacy:
        configure_legacy_model(simulation)
    previous_heading = 0.0
    unwrapped_heading = 0.0

    for previous, current in zip(rows, rows[1:]):
        dt = float(current["turn_time_s"]) - float(previous["turn_time_s"])
        turn = command_turn(previous)
        if legacy:
            left, right = action_to_tank(0.0, turn)
            simulation.data.ctrl[:] = (left, left, right, right)
            target_time = simulation.data.time + dt
            while simulation.data.time < target_time:
                mujoco.mj_step(simulation.model, simulation.data)
            heading = simulation.observe().heading_rad
        else:
            heading = simulation.step(0.0, turn, dt).heading_rad
        unwrapped_heading += angle_change(heading, previous_heading)
        previous_heading = heading
    return math.degrees(unwrapped_heading)


def validate(path: Path) -> dict[str, object]:
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    grouped: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[int(row["turn_number"])].append(row)

    turns = []
    for number, turn_rows in sorted(grouped.items()):
        physical = float(turn_rows[-1]["measured_degrees"])
        target = float(turn_rows[-1]["target_degrees"])
        legacy = replay(turn_rows, legacy=True)
        fitted = replay(turn_rows, legacy=False)
        turns.append(
            {
                "turn_number": number,
                "target_degrees": target,
                "physical_degrees": physical,
                "controller_error_degrees": target - physical,
                "legacy_sim_degrees": legacy,
                "legacy_error_degrees": legacy - physical,
                "fitted_sim_degrees": fitted,
                "fitted_error_degrees": fitted - physical,
            }
        )

    legacy_rmse = math.sqrt(
        statistics.fmean(turn["legacy_error_degrees"] ** 2 for turn in turns)
    )
    fitted_rmse = math.sqrt(
        statistics.fmean(turn["fitted_error_degrees"] ** 2 for turn in turns)
    )
    return {
        "source": str(path),
        "turns": turns,
        "summary": {
            "controller_max_error_degrees": max(
                abs(turn["controller_error_degrees"]) for turn in turns
            ),
            "legacy_model_rmse_degrees": legacy_rmse,
            "fitted_model_rmse_degrees": fitted_rmse,
            "held_out_rmse_reduction_percent": 100.0
            * (legacy_rmse - fitted_rmse)
            / legacy_rmse,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = validate(args.input)
    encoded = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
