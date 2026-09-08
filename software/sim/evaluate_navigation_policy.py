#!/usr/bin/env python3
"""Compare deterministic and learned navigation on held-out randomized worlds."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import random
import statistics

from mlp_policy import LearnedNavigationPolicy, TinyMLP
from mujoco_rover import DynamicsParameters
from navigation_env import ExpertPolicy, generate_scenarios, run_navigation_scenario


def summarize(records: list[dict[str, object]]) -> dict[str, object]:
    return {
        "episodes": len(records),
        "successes": sum(bool(record["success"]) for record in records),
        "success_rate": sum(bool(record["success"]) for record in records) / len(records),
        "collision_total": sum(int(record["collisions"]) for record in records),
        "recovery_total": sum(int(record["recoveries"]) for record in records),
        "mean_elapsed_s": statistics.fmean(float(record["elapsed_s"]) for record in records),
        "mean_path_length_m": statistics.fmean(float(record["path_length_m"]) for record in records),
    }


def evaluate(model_path: Path, count: int, seed: int) -> dict[str, object]:
    rng = random.Random(seed)
    scenarios = generate_scenarios(count, seed)
    model = TinyMLP.load(model_path)
    policies = (ExpertPolicy(), LearnedNavigationPolicy(model))
    records: dict[str, list[dict[str, object]]] = {policy.name: [] for policy in policies}
    visualizations = []

    for scenario in scenarios:
        dynamics = DynamicsParameters(
            floor_friction=rng.uniform(0.72, 1.28),
            left_turn_gain=rng.uniform(0.78, 1.04),
            right_turn_gain=rng.uniform(0.72, 1.00),
            velocity_feedback=rng.uniform(0.003, 0.007),
        )
        visual = {
            "scenario": {
                "scenario_id": scenario.scenario_id,
                "waypoints": scenario.waypoints,
                "obstacles": [asdict(obstacle) for obstacle in scenario.obstacles],
            },
            "dynamics": asdict(dynamics),
            "policies": {},
        }
        for policy in policies:
            trace: list[dict[str, object]] | None = [] if scenario.scenario_id < 8 else None
            result = run_navigation_scenario(
                scenario,
                policy,
                dynamics=dynamics,
                trace=trace,
            )
            records[policy.name].append(result.to_dict())
            if trace is not None:
                visual["policies"][policy.name] = {
                    "result": result.to_dict(),
                    "trace": trace,
                }
        if scenario.scenario_id < 8:
            visualizations.append(visual)

    fault_records: dict[str, list[dict[str, object]]] = {
        policy.name: [] for policy in policies
    }
    fault_visualizations = []
    for scenario in generate_scenarios(8, seed + 1000):
        visual = {
            "scenario": {
                "scenario_id": scenario.scenario_id,
                "waypoints": scenario.waypoints,
                "obstacles": [asdict(obstacle) for obstacle in scenario.obstacles],
            },
            "fault": {"type": "stuck_actuator", "start_s": 1.5, "end_s": 2.5},
            "policies": {},
        }
        for policy in policies:
            trace = []
            result = run_navigation_scenario(
                scenario,
                policy,
                forced_stuck_window=(1.5, 2.5),
                trace=trace,
            )
            fault_records[policy.name].append(result.to_dict())
            if scenario.scenario_id < 2:
                visual["policies"][policy.name] = {
                    "result": result.to_dict(),
                    "trace": trace,
                }
        if scenario.scenario_id < 2:
            fault_visualizations.append(visual)

    return {
        "evaluation_seed": seed,
        "domain_randomization": {
            "floor_friction": [0.72, 1.28],
            "left_turn_gain": [0.78, 1.04],
            "right_turn_gain": [0.72, 1.00],
            "velocity_feedback": [0.003, 0.007],
        },
        "summary": {name: summarize(values) for name, values in records.items()},
        "episodes": records,
        "visualizations": visualizations,
        "fault_recovery": {
            "summary": {name: summarize(values) for name, values in fault_records.items()},
            "episodes": fault_records,
            "visualizations": fault_visualizations,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=Path("artifacts/models/navigation-policy.npz"))
    parser.add_argument("--episodes", type=int, default=40)
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--output", type=Path, default=Path("artifacts/sim/navigation-policy-evaluation.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.episodes < 1:
        raise ValueError("episodes must be positive")
    result = evaluate(args.model, args.episodes, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, separators=(",", ":")) + "\n")
    print(json.dumps(result["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
