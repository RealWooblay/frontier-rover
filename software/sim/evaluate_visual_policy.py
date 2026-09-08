#!/usr/bin/env python3
"""Evaluate the deterministic visual-target controller under domain randomization."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import random

from mujoco_rover import DynamicsParameters
from visual_target_scenario import VisualTarget, run_scenario


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", type=int, default=20)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--trace-output", type=Path)
    return parser.parse_args()


def run(args: argparse.Namespace) -> int:
    if args.scenarios < 1:
        raise ValueError("scenarios must be positive")
    randomizer = random.Random(args.seed)
    records = []
    trace_records = []
    for scenario_id in range(args.scenarios):
        distance = randomizer.uniform(1.2, 2.0)
        angle = randomizer.uniform(math.radians(-25), math.radians(25))
        target = VisualTarget(
            x_m=distance * math.cos(angle),
            y_m=distance * math.sin(angle),
        )
        dynamics = DynamicsParameters(
            floor_friction=randomizer.uniform(0.7, 1.3),
            left_motor_strength=randomizer.uniform(0.85, 1.15),
            right_motor_strength=randomizer.uniform(0.85, 1.15),
        )
        scenario_trace: list[dict[str, object]] | None = [] if args.trace_output else None
        result = run_scenario(target, dynamics, trace=scenario_trace)
        for step in scenario_trace or []:
            trace_records.append(
                {"scenario_id": scenario_id, "seed": args.seed, **step}
            )
        record = {"scenario_id": scenario_id, "seed": args.seed, **result.to_dict()}
        records.append(record)
        print(json.dumps(record, separators=(",", ":")))

    successes = sum(record["success"] for record in records)
    summary = {
        "seed": args.seed,
        "scenarios": len(records),
        "successes": successes,
        "success_rate": round(successes / len(records), 3),
        "mean_elapsed_s": round(
            sum(float(record["elapsed_s"]) for record in records) / len(records), 3
        ),
    }
    print(json.dumps({"summary": summary}, separators=(",", ":")))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            "\n".join(json.dumps(record, separators=(",", ":")) for record in records)
            + "\n"
        )
    if args.trace_output:
        args.trace_output.parent.mkdir(parents=True, exist_ok=True)
        args.trace_output.write_text(
            "\n".join(
                json.dumps(record, separators=(",", ":")) for record in trace_records
            )
            + "\n"
        )
    return 0 if successes == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
