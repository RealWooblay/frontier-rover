#!/usr/bin/env python3
"""Train the navigation MLP from demonstrations in the contact MuJoCo world."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy

from high_fidelity_env import (
    FrontierRoverEnv,
    generate_scenarios,
    randomized_dynamics,
    randomized_fidelity,
)
from mlp_policy import LearnedNavigationPolicy, TinyMLP, mean_squared_error
from navigation_env import ExpertPolicy, NavigationObservation, NavigationPolicy


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = ROOT / "artifacts/models/high-fidelity-navigation-policy.npz"
DEFAULT_REPORT = ROOT / "artifacts/models/high-fidelity-navigation-policy-training.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def collect_demonstrations(
    *,
    scenario_count: int,
    scenario_seed: int,
    behavior_policy: NavigationPolicy | None = None,
) -> tuple[numpy.ndarray, numpy.ndarray, dict[str, object]]:
    """Run a behavior policy while recording what the expert would do."""
    inputs: list[tuple[float, ...]] = []
    targets: list[tuple[float, float]] = []
    successes = 0
    contacts = 0
    episodes = []
    scenarios = generate_scenarios(scenario_count, scenario_seed)
    for index, scenario in enumerate(scenarios):
        dynamics = randomized_dynamics(scenario_seed * 100 + index)
        fidelity = randomized_fidelity(scenario_seed * 100 + index + 50_000)
        expert = ExpertPolicy()
        behavior = behavior_policy or expert
        reset = getattr(behavior, "reset", None)
        if callable(reset):
            reset()
        expert.reset()
        env = FrontierRoverEnv(
            scenario,
            dynamics=dynamics,
            fidelity=fidelity,
            max_duration_s=24.0,
        )
        observation, _info = env.reset(seed=scenario_seed + index)
        terminated = False
        truncated = False
        steps = 0
        try:
            while not (terminated or truncated):
                nav_observation = NavigationObservation(*map(float, observation))
                label = expert.act(nav_observation)
                command = label if behavior_policy is None else behavior.act(nav_observation)
                inputs.append(nav_observation.vector())
                targets.append((label.forward, label.turn))
                observation, _reward, terminated, truncated, info = env.step(
                    numpy.asarray((command.forward, command.turn), dtype=numpy.float32)
                )
                steps += 1
            successes += int(terminated)
            contacts += int(info["contact_episodes"])
            episodes.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "behavior": behavior.name,
                    "success": terminated,
                    "steps": steps,
                    "contact_episodes": info["contact_episodes"],
                    "final_goal_distance_m": info["goal_distance_m"],
                }
            )
        finally:
            env.close()
    return (
        numpy.asarray(inputs, dtype=numpy.float64),
        numpy.asarray(targets, dtype=numpy.float64),
        {
            "scenarios": scenario_count,
            "samples": len(inputs),
            "behavior_successes": successes,
            "contact_episodes": contacts,
            "episodes": episodes,
        },
    )


def train(
    model_path: Path = DEFAULT_MODEL,
    report_path: Path = DEFAULT_REPORT,
    *,
    seed: int = 1701,
    initial_scenarios: int = 80,
    dagger_scenarios: int = 30,
    dagger_rounds: int = 2,
) -> dict[str, object]:
    train_x, train_y, initial_collection = collect_demonstrations(
        scenario_count=initial_scenarios,
        scenario_seed=seed,
    )
    validation_x, validation_y, validation_collection = collect_demonstrations(
        scenario_count=24,
        scenario_seed=seed + 10_000,
    )
    model = TinyMLP(hidden_size=32, seed=seed)
    initial_mse = mean_squared_error(model.predict(validation_x), validation_y)
    histories = []
    history = model.fit(
        train_x,
        train_y,
        validation_x,
        validation_y,
        epochs=180,
        batch_size=256,
        learning_rate=0.0025,
        seed=seed,
        turn_loss_weight=5.0,
    )
    histories.append(
        {
            "round": 0,
            "kind": "expert_behavior_cloning",
            "train_loss": history.train_loss,
            "validation_loss": history.validation_loss,
        }
    )
    dagger_collections = []
    for round_index in range(dagger_rounds):
        learned = LearnedNavigationPolicy(model)
        round_x, round_y, collection = collect_demonstrations(
            scenario_count=dagger_scenarios,
            scenario_seed=seed + 20_000 + round_index * 1_000,
            behavior_policy=learned,
        )
        train_x = numpy.concatenate((train_x, round_x))
        train_y = numpy.concatenate((train_y, round_y))
        history = model.fit(
            train_x,
            train_y,
            validation_x,
            validation_y,
            epochs=100,
            batch_size=256,
            learning_rate=0.0015,
            seed=seed + round_index + 1,
            turn_loss_weight=5.0,
        )
        histories.append(
            {
                "round": round_index + 1,
                "kind": "dataset_aggregation",
                "train_loss": history.train_loss,
                "validation_loss": history.validation_loss,
            }
        )
        dagger_collections.append(collection)

    model_path.parent.mkdir(parents=True, exist_ok=True)
    model.save(model_path)
    final_mse = mean_squared_error(model.predict(validation_x), validation_y)
    report = {
        "schema_version": 1,
        "method": "behavior cloning plus DAgger in contact-physical MuJoCo",
        "seed": seed,
        "observation_names": [
            "goal_distance",
            "goal_error",
            "front_clearance",
            "left_clearance",
            "right_clearance",
            "forward_velocity",
            "yaw_rate",
            "collision",
            "stuck",
        ],
        "action_names": ["forward", "turn"],
        "network": {"shape": [9, 32, 2], "parameters": 386, "activation": "tanh"},
        "initial_validation_mse": initial_mse,
        "final_validation_mse": final_mse,
        "training_samples": len(train_x),
        "validation_samples": len(validation_x),
        "initial_collection": initial_collection,
        "dagger_collections": dagger_collections,
        "validation_collection": validation_collection,
        "history": histories,
        "model_path": _display_path(model_path),
        "model_sha256": _sha256(model_path),
        "truth_boundary": (
            "MuJoCo truth generates reward and evaluation metrics; expert and learned "
            "policies receive the same nine imperfect observation values"
        ),
        "deployment_gap": (
            "physical rover lacks the metric range and translational state inputs used here"
        ),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--seed", type=int, default=1701)
    parser.add_argument("--initial-scenarios", type=int, default=80)
    parser.add_argument("--dagger-scenarios", type=int, default=30)
    parser.add_argument("--dagger-rounds", type=int, default=2)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = train(
        args.model,
        args.report,
        seed=args.seed,
        initial_scenarios=args.initial_scenarios,
        dagger_scenarios=args.dagger_scenarios,
        dagger_rounds=args.dagger_rounds,
    )
    print(
        json.dumps(
            {
                "training_samples": report["training_samples"],
                "initial_validation_mse": report["initial_validation_mse"],
                "final_validation_mse": report["final_validation_mse"],
                "model_sha256": report["model_sha256"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
