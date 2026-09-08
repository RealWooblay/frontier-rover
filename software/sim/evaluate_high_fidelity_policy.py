#!/usr/bin/env python3
"""Held-out comparison of expert and learned policies in the contact world."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics

from high_fidelity_env import (
    generate_scenarios,
    randomized_dynamics,
    randomized_fidelity,
    run_policy_episode,
)
from mlp_policy import LearnedNavigationPolicy, TinyMLP
from navigation_env import ExpertPolicy
from train_high_fidelity_policy import DEFAULT_MODEL


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "artifacts/sim/high-fidelity-policy-evaluation.json"


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def _summary(records: list[dict[str, object]]) -> dict[str, object]:
    successes = [record for record in records if record["success"]]
    return {
        "episodes": len(records),
        "successes": len(successes),
        "success_rate": len(successes) / max(1, len(records)),
        "contact_episodes": sum(int(record["contact_episodes"]) for record in records),
        "recoveries": sum(int(record["recoveries"]) for record in records),
        "mean_reward": statistics.fmean(float(record["reward_total"]) for record in records),
        "mean_elapsed_s_successes": (
            statistics.fmean(float(record["elapsed_s"]) for record in successes)
            if successes
            else None
        ),
        "mean_final_pose_error_m": statistics.fmean(
            float(record["final_pose_error_m"]) for record in records
        ),
    }


def evaluate(
    model_path: Path = DEFAULT_MODEL,
    *,
    count: int = 40,
    seed: int = 9201,
    fault_count: int = 12,
) -> dict[str, object]:
    model = TinyMLP.load(model_path)
    policy_factories = {
        "deterministic_expert": ExpertPolicy,
        "high_fidelity_learned_mlp": lambda: LearnedNavigationPolicy(model),
    }
    records: dict[str, list[dict[str, object]]] = {name: [] for name in policy_factories}
    scenarios = generate_scenarios(count, seed)
    for index, scenario in enumerate(scenarios):
        dynamics = randomized_dynamics(seed * 100 + index)
        fidelity = randomized_fidelity(seed * 100 + index + 50_000)
        for name, factory in policy_factories.items():
            episode = run_policy_episode(
                scenario,
                factory(),
                dynamics=dynamics,
                fidelity=fidelity,
                seed=seed + index,
            )
            records[name].append(episode["result"])

    fault_records: dict[str, list[dict[str, object]]] = {
        name: [] for name in policy_factories
    }
    for index, scenario in enumerate(generate_scenarios(fault_count, seed + 100_000)):
        dynamics = randomized_dynamics(seed * 200 + index)
        fidelity = randomized_fidelity(seed * 200 + index + 50_000)
        for name, factory in policy_factories.items():
            episode = run_policy_episode(
                scenario,
                factory(),
                dynamics=dynamics,
                fidelity=fidelity,
                seed=seed + 100_000 + index,
                forced_stuck_window=(1.5, 2.5),
            )
            fault_records[name].append(episode["result"])

    return {
        "schema_version": 1,
        "experiment": "high-fidelity learned-policy transfer candidate",
        "model": {
            "path": _display_path(model_path),
            "sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        },
        "evaluation_seed": seed,
        "scenario_count": count,
        "domain_randomization": {
            "dynamics": {
                "floor_friction": [0.72, 1.28],
                "left_turn_gain": [0.82, 0.98],
                "right_turn_gain": [0.76, 0.94],
                "velocity_feedback": [0.0032, 0.0065],
                "drive_scale": [0.90, 1.10],
            },
            "sensors": {
                "range_noise_sigma_m": [0.004, 0.035],
                "range_dropout_probability": [0.0, 0.045],
                "range_latency_ms": [0, 120],
                "command_latency_ms": [0, 100],
                "odometry_scale": [0.93, 1.07],
                "gyro_scale": [0.97, 1.04],
            },
        },
        "summary": {name: _summary(values) for name, values in records.items()},
        "episodes": records,
        "fault_recovery": {
            "fault": {"kind": "complete actuator stall", "start_s": 1.5, "end_s": 2.5},
            "summary": {name: _summary(values) for name, values in fault_records.items()},
            "episodes": fault_records,
        },
        "truth_boundary": (
            "both policies receive identical imperfect observations; MuJoCo truth is scoring only"
        ),
        "physical_status": "not transferred; required observation parity is absent",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--episodes", type=int, default=40)
    parser.add_argument("--fault-episodes", type=int, default=12)
    parser.add_argument("--seed", type=int, default=9201)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact = evaluate(
        args.model,
        count=args.episodes,
        seed=args.seed,
        fault_count=args.fault_episodes,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"nominal": artifact["summary"], "fault": artifact["fault_recovery"]["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
