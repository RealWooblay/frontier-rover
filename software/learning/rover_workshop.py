#!/usr/bin/env python3
"""Laptop exercises using actual rover functions; never connect to hardware."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
for directory in ("jetson", "pi", "sim", "shared"):
    sys.path.insert(0, str(ROOT / "software" / directory))


def vision(args: argparse.Namespace) -> dict:
    from autonomy_controller import Observation, TargetController
    from mission_runtime import RuntimeConfig, SearchProgress, plan_execution
    from remote_control import MotorCalibration, speeds_for_action
    from yolo_perception import measure_box

    config = RuntimeConfig()
    detection = None if args.lost else measure_box(
        49, "orange", 0.78, tuple(args.box), 640, 360, source="classroom"
    )
    observation = Observation(
        target_visible=detection is not None,
        horizontal_error=detection.horizontal_error if detection else 0.0,
        area_ratio=detection.area_ratio if detection else 0.0,
        bottom_edge_ratio=detection.bottom_edge_ratio if detection else 0.0,
        frame_age_ms=args.frame_age_ms,
    )
    controller = TargetController(config.controller_config())
    action = controller.update(observation)
    operation = plan_execution(action, observation, config, SearchProgress())
    pwm = None
    if operation.kind.value != "heading_turn":
        pwm = speeds_for_action(
            operation.action.forward, operation.action.turn,
            MotorCalibration(left_pwm=args.left_scale, right_pwm=args.right_scale),
        )
    return {
        "provenance": "classroom box; actual pure geometry/controller/mixer code; no YOLO inference",
        "hardware_contacted": False,
        "runtime_defaults_not_live_configuration": asdict(config),
        "box": detection.to_dict() if detection else None,
        "observation": asdict(observation),
        "operation": operation.to_dict(),
        "calibration_assumed": {"left": args.left_scale, "right": args.right_scale},
        "signed_pwm_fraction": pwm,
        "note": "Heading turns use gyro feedback; their instantaneous PWM cannot be inferred from this box.",
    }


def gradient(_args: argparse.Namespace) -> dict:
    import numpy as np
    from mlp_policy import TinyMLP
    from navigation_env import ExpertPolicy, NavigationObservation

    model_path = ROOT / "artifacts/models/high-fidelity-navigation-policy.npz"
    original_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    model = TinyMLP.load(model_path)
    inputs = np.asarray([[0.6, 0.25, 0.8, 0.9, 0.5, 0.0, 0.0, 0.0, 0.0]])
    expert = ExpertPolicy()
    expert.reset()
    target_action = expert.act(NavigationObservation(*inputs[0]))
    target = np.asarray([[target_action.forward, target_action.turn]])
    hidden, output = model.forward(inputs)
    loss_weights = np.asarray([1.0, 5.0])

    def loss() -> float:
        error = model.predict(inputs) - target
        return float(np.sum(error * error * loss_weights) / loss_weights.sum())

    initial_loss = loss()
    d_output = 2.0 * (output - target) * loss_weights / loss_weights.sum()
    d_z2 = d_output * (1.0 - output * output)
    d_z1 = (d_z2 @ model.w2.T) * (1.0 - hidden * hidden)
    gradients = {
        "w2": hidden.T @ d_z2,
        "b2": d_z2.sum(axis=0),
        "w1": inputs.T @ d_z1,
        "b1": d_z1.sum(axis=0),
    }
    index = tuple(map(int, np.unravel_index(np.abs(gradients["w1"]).argmax(), model.w1.shape)))
    before = float(model.w1[index])
    analytic = float(gradients["w1"][index])
    epsilon = 1e-5
    model.w1[index] = before + epsilon
    plus = loss()
    model.w1[index] = before - epsilon
    minus = loss()
    model.w1[index] = before
    numerical = (plus - minus) / (2.0 * epsilon)
    if not np.isclose(analytic, numerical, rtol=1e-4, atol=1e-7):
        raise AssertionError("analytic gradient disagrees with finite differences")
    learning_rate = 0.001
    for name, parameter in model.parameters.items():
        parameter -= learning_rate * gradients[name]
    final_loss = loss()
    if final_loss >= initial_loss:
        raise AssertionError("this classroom gradient step did not reduce loss")
    if hashlib.sha256(model_path.read_bytes()).hexdigest() != original_hash:
        raise AssertionError("saved model changed")
    return {
        "provenance": "saved navigation network, classroom observation, baseline-generated label",
        "input": inputs[0].tolist(), "target": target[0].tolist(),
        "prediction_before": output[0].tolist(),
        "prediction_after": model.predict(inputs)[0].tolist(),
        "selected_weight": f"w1{index}", "weight_before": before,
        "analytic_gradient": analytic, "finite_difference_gradient": numerical,
        "learning_rate": learning_rate, "weight_after": float(model.w1[index]),
        "weighted_loss_before": initial_loss, "weighted_loss_after": final_loss,
        "saved_model_unchanged": True,
        "note": "One SGD teaching step in memory. The original multi-sample training uses Adam.",
    }


def compare(args: argparse.Namespace) -> dict:
    import numpy as np
    from high_fidelity_env import (
        generate_scenarios, randomized_dynamics, randomized_fidelity, run_policy_episode,
    )
    from mlp_policy import LearnedNavigationPolicy, ShieldedNavigationPolicy, TinyMLP
    from navigation_env import ExpertPolicy, NavigationAction

    if not 1 <= args.episodes <= 100:
        raise ValueError("episodes must be between 1 and 100")
    path = ROOT / "artifacts/models/high-fidelity-navigation-policy.npz"
    model = TinyMLP.load(path)

    class BoundedMLP:
        name = "bounded_mlp_without_shield"

        def act(self, observation):
            output = model.predict(np.asarray(observation.vector()))
            return NavigationAction(
                float(np.clip(output[0], -0.35, 0.65)),
                float(np.clip(output[1], -0.18, 0.18)), "learned_track",
            )

    factories = {
        "baseline": ExpertPolicy,
        "baseline_with_shield": lambda: ShieldedNavigationPolicy(ExpertPolicy()),
        "bounded_mlp": BoundedMLP,
        "bounded_mlp_with_shield": lambda: LearnedNavigationPolicy(model),
    }
    records = {name: [] for name in factories}
    for index, scenario in enumerate(generate_scenarios(args.episodes, args.seed)):
        dynamics = randomized_dynamics(args.seed * 100 + index)
        fidelity = randomized_fidelity(args.seed * 100 + index + 50_000)
        for name, factory in factories.items():
            episode = run_policy_episode(
                scenario, factory(), dynamics=dynamics, fidelity=fidelity,
                seed=args.seed + index,
            )
            records[name].append(episode["result"])
        print(f"Compared scenario {index + 1}/{args.episodes}", file=sys.stderr, flush=True)
    summary = {
        name: {
            "missions": len(rows), "successes": sum(row["success"] for row in rows),
            "contact_events": sum(row["contact_episodes"] for row in rows),
            "missions_with_contact": sum(row["contact_episodes"] > 0 for row in rows),
        }
        for name, rows in records.items()
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "four-way controller ablation on fresh seeded contact worlds",
        "seed": args.seed, "model_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "summary": summary, "episodes": records,
        "interpretation": [
            "Same world, parameter distributions, and random seed per controller; trajectories differ.",
            "Within each family, shield on/off isolates its contribution on these runs.",
            "Baseline and learned families have different output bounds; this is not architecture-only attribution.",
            "Collision is an ideal simulator contact signal; stuck includes true movement and injected-fault state.",
            "Known initial pose and goal coordinates are assumptions. Physical transfer is untested.",
            "A small selected scenario suite is engineering evidence, not a general safety guarantee.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="lesson", required=True)
    boxes = commands.add_parser("vision", help="trace a classroom detection through existing control code")
    boxes.add_argument("--box", nargs=4, type=float, default=[440, 180, 520, 260])
    boxes.add_argument("--lost", action="store_true")
    boxes.add_argument("--frame-age-ms", type=int, default=100)
    boxes.add_argument("--left-scale", type=float, default=0.8)
    boxes.add_argument("--right-scale", type=float, default=1.0)
    boxes.set_defaults(run=vision)
    commands.add_parser("gradient", help="inspect and verify one weight update").set_defaults(run=gradient)
    comparisons = commands.add_parser("compare", help="run four policies in identical seeded scenarios")
    comparisons.add_argument("--episodes", type=int, default=12)
    comparisons.add_argument("--seed", type=int, default=260908)
    comparisons.add_argument("--output", type=Path)
    comparisons.set_defaults(run=compare)
    args = parser.parse_args()
    if getattr(args, "output", None) and args.output.exists():
        parser.error("output already exists; choose a new path to preserve the earlier run")
    result = args.run(args)
    if getattr(args, "output", None):
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
        print(json.dumps({"output": str(args.output), "summary": result["summary"]}, indent=2))
    else:
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
