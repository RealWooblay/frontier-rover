#!/usr/bin/env python3
"""Dependency-light Jetson runtime for the trained navigation MLP artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy


INPUT_NAMES = (
    "goal_distance",
    "goal_error",
    "front_clearance",
    "left_clearance",
    "right_clearance",
    "forward_velocity",
    "yaw_rate",
    "collision",
    "stuck",
)


class NavigationPolicyRuntime:
    def __init__(self, artifact: Path) -> None:
        values = numpy.load(artifact)
        self.w1 = values["w1"]
        self.b1 = values["b1"]
        self.w2 = values["w2"]
        self.b2 = values["b2"]
        if (
            self.w1.shape != (9, 32)
            or self.b1.shape != (32,)
            or self.w2.shape != (32, 2)
            or self.b2.shape != (2,)
        ):
            raise ValueError("policy artifact does not have the expected 9-32-2 shape")

    def predict(self, observation: dict[str, float]) -> dict[str, object]:
        missing = set(INPUT_NAMES) - set(observation)
        if missing:
            raise ValueError(f"missing policy inputs: {sorted(missing)}")
        inputs = numpy.asarray([float(observation[name]) for name in INPUT_NAMES])
        hidden = numpy.tanh(inputs @ self.w1 + self.b1)
        output = numpy.tanh(hidden @ self.w2 + self.b2)

        if observation["collision"] > 0.5 or observation["stuck"] > 0.5:
            turn = -0.12 if observation["left_clearance"] > observation["right_clearance"] else 0.12
            forward, mode = -0.24, "safety_recovery"
        elif observation["front_clearance"] < 0.24:
            turn = -0.15 if observation["left_clearance"] > observation["right_clearance"] else 0.15
            forward, mode = 0.06, "safety_avoid"
        else:
            forward = float(numpy.clip(output[0], -0.35, 0.65))
            turn = float(numpy.clip(output[1], -0.18, 0.18))
            mode = "learned"
        return {
            "forward": forward,
            "turn": turn,
            "mode": mode,
            "hidden_activation_min": float(hidden.min()),
            "hidden_activation_max": float(hidden.max()),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("observation", help="JSON object containing all nine inputs")
    args = parser.parse_args()
    result = NavigationPolicyRuntime(args.artifact).predict(json.loads(args.observation))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
