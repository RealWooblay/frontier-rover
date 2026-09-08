#!/usr/bin/env python3
"""Run one bounded rover action in MuJoCo and print the resulting state."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json

from mujoco_rover import RoverSimulation


def bounded(value: str) -> float:
    number = float(value)
    if not -1.0 <= number <= 1.0:
        raise argparse.ArgumentTypeError("must be between -1 and 1")
    return number


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forward", type=bounded, default=0.0)
    parser.add_argument("--turn", type=bounded, default=0.0)
    parser.add_argument("--seconds", type=float, default=1.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    simulation = RoverSimulation()
    observation = simulation.step(args.forward, args.turn, args.seconds)
    print(
        json.dumps(
            {
                "action": {"forward": args.forward, "turn": args.turn},
                "observation": asdict(observation),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
