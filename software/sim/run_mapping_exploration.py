#!/usr/bin/env python3
"""Run the canonical mapping experiment and persist replayable evidence."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path

from exploration_scenario import ExplorationWorld, FidelityParameters, run_exploration
from mujoco_rover import DynamicsParameters
from visual_target_scenario import VisualTarget


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/sim/2026-09-06-mapping-exploration.json"),
    )
    parser.add_argument("--target-x", type=float, default=1.35)
    parser.add_argument("--target-y", type=float, default=0.90)
    parser.add_argument("--odometry-scale", type=float, default=0.97)
    parser.add_argument("--gyro-scale", type=float, default=1.015)
    parser.add_argument("--gyro-bias-dps", type=float, default=0.10)
    parser.add_argument("--geometry-camera", action="store_true")
    args = parser.parse_args()

    world = ExplorationWorld(target=VisualTarget(args.target_x, args.target_y))
    dynamics = DynamicsParameters()
    fidelity = FidelityParameters(rendered_camera=not args.geometry_camera)
    trace: list[dict[str, object]] = []
    camera_frames: list[dict[str, object]] = []
    result = run_exploration(
        world=world,
        dynamics=dynamics,
        fidelity=fidelity,
        odometry_scale=args.odometry_scale,
        gyro_scale=args.gyro_scale,
        gyro_bias_dps=args.gyro_bias_dps,
        trace=trace,
        camera_frames=camera_frames,
    )
    artifact = {
        "schema_version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "experiment": "sensor-driven-hidden-target-mapping",
        "inputs": {
            "world": asdict(world),
            "dynamics": asdict(dynamics),
            "fidelity": asdict(fidelity),
            "odometry_scale": args.odometry_scale,
            "gyro_scale": args.gyro_scale,
            "gyro_bias_dps": args.gyro_bias_dps,
        },
        "result": result,
        "trace": trace,
        "provenance": {
            "physics": "MuJoCo rover, floor, wall, wheel, and obstacle contacts",
            "planner_inputs": "estimated pose, occupancy map, delayed/noisy MuJoCo rays, and delayed image-derived detection",
            "ground_truth_use": "physics, sensor generation, scoring, and optional truth overlay only",
            "camera": "MuJoCo rendered RGB processed by orange-pixel segmentation",
            "collision_response": "MuJoCo contact solver; no teleport or snap-back",
            "physical_gap": "The rover has no metric range sensor or wheel encoders, so this map is not claimed as a physical-rover result.",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "success": result["success"],
                "terminal_state": result["terminal_state"],
                "elapsed_s": result["elapsed_s"],
                "pose_error_m": result["pose_error_m"],
                "collisions": result["collisions"],
                "replans": result["replans"],
            },
            indent=2,
        )
    )
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
