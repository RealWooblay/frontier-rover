#!/usr/bin/env python3
"""Run reproducible randomized high-fidelity exploration acceptance trials."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date
import json
import math
from pathlib import Path
import random

from exploration_scenario import (
    ExplorationWorld,
    FidelityParameters,
    run_exploration,
)
from mujoco_rover import DynamicsParameters
from navigation_env import CircleObstacle
from visual_target_scenario import VisualTarget


ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class RandomizedTrial:
    trial_id: int
    world: ExplorationWorld
    dynamics: DynamicsParameters
    fidelity: FidelityParameters
    odometry_scale: float
    gyro_scale: float
    gyro_bias_dps: float


def _clear_of(
    point: tuple[float, float],
    obstacles: list[CircleObstacle],
    margin_m: float,
) -> bool:
    return all(
        math.hypot(point[0] - obstacle.x_m, point[1] - obstacle.y_m)
        > obstacle.radius_m + margin_m
        for obstacle in obstacles
    )


def generate_trials(count: int, seed: int, *, rendered_camera: bool) -> list[RandomizedTrial]:
    if count < 1:
        raise ValueError("count must be positive")
    rng = random.Random(seed)
    trials = []
    start = (-1.45, -0.95)
    for trial_id in range(count):
        obstacles: list[CircleObstacle] = []
        while len(obstacles) < 2:
            candidate = CircleObstacle(
                rng.uniform(-0.75, 1.05),
                rng.uniform(-0.75, 0.75),
                rng.uniform(0.18, 0.31),
            )
            if math.hypot(candidate.x_m - start[0], candidate.y_m - start[1]) < 0.65:
                continue
            if not _clear_of((candidate.x_m, candidate.y_m), obstacles, 0.24):
                continue
            obstacles.append(candidate)
        while True:
            target = (rng.uniform(-0.20, 1.55), rng.uniform(-1.0, 1.05))
            if math.hypot(target[0] - start[0], target[1] - start[1]) < 1.2:
                continue
            if _clear_of(target, obstacles, 0.32):
                break
        dynamics = DynamicsParameters(
            floor_friction=rng.uniform(0.75, 1.25),
            left_turn_gain=0.90 * rng.uniform(0.92, 1.08),
            right_turn_gain=0.84 * rng.uniform(0.92, 1.08),
            velocity_feedback=rng.uniform(0.003, 0.006),
            left_drive_scale=rng.uniform(0.90, 1.10),
            right_drive_scale=rng.uniform(0.90, 1.10),
        )
        fidelity = FidelityParameters(
            seed=seed * 1000 + trial_id,
            range_noise_sigma_m=rng.uniform(0.005, 0.03),
            range_dropout_probability=rng.uniform(0.0, 0.04),
            range_latency_ms=rng.randint(20, 120),
            camera_period_ms=rng.randint(80, 150),
            camera_latency_ms=rng.randint(50, 180),
            camera_dropout_probability=rng.uniform(0.0, 0.05),
            command_latency_ms=rng.randint(20, 100),
            odometry_noise_sigma_mps=rng.uniform(0.004, 0.02),
            gyro_noise_sigma_dps=rng.uniform(0.05, 0.40),
            rendered_camera=rendered_camera,
        )
        trials.append(
            RandomizedTrial(
                trial_id=trial_id,
                world=ExplorationWorld(
                    obstacles=tuple(obstacles),
                    target=VisualTarget(*target),
                ),
                dynamics=dynamics,
                fidelity=fidelity,
                odometry_scale=rng.uniform(0.94, 1.03),
                gyro_scale=rng.uniform(0.99, 1.03),
                gyro_bias_dps=rng.uniform(-0.4, 0.4),
            )
        )
    return trials


def evaluate(count: int, seed: int, *, rendered_camera: bool) -> dict[str, object]:
    rows = []
    for trial in generate_trials(count, seed, rendered_camera=rendered_camera):
        result = run_exploration(
            world=trial.world,
            dynamics=trial.dynamics,
            fidelity=trial.fidelity,
            duration_s=50.0,
            odometry_scale=trial.odometry_scale,
            gyro_scale=trial.gyro_scale,
            gyro_bias_dps=trial.gyro_bias_dps,
        )
        rows.append(
            {
                "trial_id": trial.trial_id,
                "world": {
                    "obstacles": [asdict(item) for item in trial.world.obstacles],
                    "target": asdict(trial.world.target),
                },
                "dynamics": asdict(trial.dynamics),
                "fidelity": asdict(trial.fidelity),
                "odometry_scale": trial.odometry_scale,
                "gyro_scale": trial.gyro_scale,
                "gyro_bias_dps": trial.gyro_bias_dps,
                "result": {
                    key: result[key]
                    for key in (
                        "success",
                        "terminal_state",
                        "elapsed_s",
                        "target_seen",
                        "collisions",
                        "replans",
                        "final_distance_m",
                        "pose_error_m",
                    )
                },
            }
        )
    successes = [row for row in rows if row["result"]["success"]]
    return {
        "experiment": "domain-randomized contact-physical hidden-target exploration",
        "date": date.today().isoformat(),
        "seed": seed,
        "rendered_camera": rendered_camera,
        "summary": {
            "trials": count,
            "successes": len(successes),
            "success_rate": len(successes) / count,
            "collision_free_trials": sum(row["result"]["collisions"] == 0 for row in rows),
            "mean_pose_error_m": sum(row["result"]["pose_error_m"] for row in rows) / count,
            "mean_elapsed_s_successes": (
                sum(row["result"]["elapsed_s"] for row in successes) / len(successes)
                if successes
                else None
            ),
        },
        "truth_boundary": "ground truth is used by MuJoCo physics and scoring, never planner input",
        "parameter_status": "turn response measured; translation, friction, mass, range, and latency distributions assumed",
        "trials": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--seed", type=int, default=907)
    parser.add_argument("--geometry-camera", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts/sim/2026-09-06-high-fidelity-exploration.json",
    )
    args = parser.parse_args()
    artifact = evaluate(args.count, args.seed, rendered_camera=not args.geometry_camera)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2) + "\n")
    print(json.dumps(artifact["summary"], indent=2))
    print(args.output)


if __name__ == "__main__":
    main()
