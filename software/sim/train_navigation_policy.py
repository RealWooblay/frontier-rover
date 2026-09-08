#!/usr/bin/env python3
"""Train an inspectable perception-feature-to-motion policy by imitation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy

from mlp_policy import INPUT_NAMES, OUTPUT_NAMES, LearnedNavigationPolicy, TinyMLP
from navigation_env import (
    ExpertPolicy,
    NavigationObservation,
    expert_action,
    generate_scenarios,
    run_navigation_scenario,
)


def build_dataset(seed: int, synthetic_samples: int = 12000):
    rng = numpy.random.default_rng(seed)
    observations = []
    actions = []

    for scenario in generate_scenarios(80, seed):
        trace: list[dict[str, object]] = []
        run_navigation_scenario(scenario, ExpertPolicy(), trace=trace)
        for row in trace[::2]:
            observation = row["observation"]
            action = row["action"]
            observations.append([float(observation[name]) for name in INPUT_NAMES])
            actions.append([float(action[name]) for name in OUTPUT_NAMES])

    for _ in range(synthetic_samples):
        collision = float(rng.random() < 0.035)
        stuck = float(not collision and rng.random() < 0.035)
        observation = NavigationObservation(
            goal_distance=float(rng.uniform(0.0, 1.0)),
            goal_error=float(rng.uniform(-1.0, 1.0)),
            front_clearance=float(rng.uniform(0.0, 1.0)),
            left_clearance=float(rng.uniform(0.0, 1.0)),
            right_clearance=float(rng.uniform(0.0, 1.0)),
            forward_velocity=float(rng.uniform(-0.6, 0.8)),
            yaw_rate=float(rng.uniform(-0.8, 0.8)),
            collision=collision,
            stuck=stuck,
        )
        action = expert_action(observation)
        observations.append(observation.vector())
        actions.append((action.forward, action.turn))

    x = numpy.asarray(observations, dtype=numpy.float64)
    y = numpy.asarray(actions, dtype=numpy.float64)
    order = rng.permutation(len(x))
    validation_count = max(1, round(len(x) * 0.2))
    validation = order[:validation_count]
    train = order[validation_count:]
    return x[train], y[train], x[validation], y[validation]


def aggregate_learner_states(
    model: TinyMLP, seed: int, scenario_count: int = 50
) -> tuple[numpy.ndarray, numpy.ndarray]:
    observations = []
    actions = []
    policy = LearnedNavigationPolicy(model)
    for scenario in generate_scenarios(scenario_count, seed):
        trace: list[dict[str, object]] = []
        run_navigation_scenario(scenario, policy, trace=trace)
        for row in trace:
            values = row["observation"]
            observation = NavigationObservation(
                **{name: float(values[name]) for name in INPUT_NAMES}
            )
            correction = expert_action(observation)
            observations.append(observation.vector())
            actions.append((correction.forward, correction.turn))
    return numpy.asarray(observations), numpy.asarray(actions)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=23)
    parser.add_argument("--epochs", type=int, default=220)
    parser.add_argument("--model", type=Path, default=Path("artifacts/models/navigation-policy.npz"))
    parser.add_argument("--report", type=Path, default=Path("artifacts/models/navigation-policy-training.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    train_x, train_y, validation_x, validation_y = build_dataset(args.seed)
    model = TinyMLP(seed=args.seed)
    initial_validation = float(numpy.mean((model.predict(validation_x) - validation_y) ** 2))
    history = model.fit(
        train_x,
        train_y,
        validation_x,
        validation_y,
        epochs=args.epochs,
        seed=args.seed,
    )
    aggregation_rounds = []
    for round_index in range(3):
        aggregate_x, aggregate_y = aggregate_learner_states(
            model, args.seed + 100 + round_index, scenario_count=40
        )
        train_x = numpy.concatenate((train_x, aggregate_x))
        train_y = numpy.concatenate((train_y, aggregate_y))
        round_history = model.fit(
            train_x,
            train_y,
            validation_x,
            validation_y,
            epochs=80,
            seed=args.seed + round_index + 1,
        )
        history.train_loss.extend(round_history.train_loss)
        history.validation_loss.extend(round_history.validation_loss)
        aggregation_rounds.append(
            {
                "round": round_index + 1,
                "new_learner_states": len(aggregate_x),
                "combined_training_samples": len(train_x),
                "validation_mse": round_history.validation_loss[-1],
            }
        )
    model.save(args.model)
    digest = hashlib.sha256(args.model.read_bytes()).hexdigest()
    report = {
        "seed": args.seed,
        "epochs": args.epochs,
        "training_samples": len(train_x),
        "validation_samples": len(validation_x),
        "inputs": INPUT_NAMES,
        "outputs": OUTPUT_NAMES,
        "hidden_units": len(model.b1),
        "parameter_count": sum(value.size for value in model.parameters.values()),
        "initial_validation_mse": initial_validation,
        "final_training_mse": history.train_loss[-1],
        "final_validation_mse": history.validation_loss[-1],
        "dataset_aggregation": aggregation_rounds,
        "history": {
            "train": history.train_loss,
            "validation": history.validation_loss,
        },
        "model": str(args.model),
        "model_sha256": digest,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "history"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
