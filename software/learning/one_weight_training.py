#!/usr/bin/env python3
"""Show gradient descent by fitting one rover turn-response weight."""

from __future__ import annotations

import argparse
from dataclasses import dataclass


# Classroom data, not measurements from the physical rover.
# Each pair means: (PWM command, observed turn rate in degrees per second).
SAMPLES = (
    (0.25, 15.0),
    (0.50, 30.0),
    (0.75, 45.0),
    (1.00, 60.0),
)


@dataclass(frozen=True)
class TrainingStep:
    number: int
    weight_before: float
    predictions: tuple[float, ...]
    errors: tuple[float, ...]
    loss: float
    gradient: float
    weight_change: float
    weight_after: float


def evaluate(weight: float) -> tuple[tuple[float, ...], tuple[float, ...], float, float]:
    """Return predictions, errors, mean-squared loss, and d(loss)/d(weight)."""
    predictions = tuple(weight * command for command, _target in SAMPLES)
    errors = tuple(
        prediction - target
        for prediction, (_command, target) in zip(predictions, SAMPLES)
    )
    loss = sum(error**2 for error in errors) / len(SAMPLES)
    gradient = (
        2.0
        * sum(error * command for error, (command, _target) in zip(errors, SAMPLES))
        / len(SAMPLES)
    )
    return predictions, errors, loss, gradient


def train(
    *,
    start_weight: float = 0.0,
    learning_rate: float = 0.5,
    steps: int = 8,
) -> list[TrainingStep]:
    weight = start_weight
    history: list[TrainingStep] = []
    for number in range(1, steps + 1):
        predictions, errors, loss, gradient = evaluate(weight)
        weight_change = -learning_rate * gradient
        weight_after = weight + weight_change
        history.append(
            TrainingStep(
                number=number,
                weight_before=weight,
                predictions=predictions,
                errors=errors,
                loss=loss,
                gradient=gradient,
                weight_change=weight_change,
                weight_after=weight_after,
            )
        )
        weight = weight_after
    return history


def values(items: tuple[float, ...]) -> str:
    return "[" + ", ".join(f"{item:7.3f}" for item in items) + "]"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=0.5)
    parser.add_argument("--start-weight", type=float, default=0.0)
    args = parser.parse_args()

    print("MODEL: predicted_turn_rate = weight * pwm_command")
    print("DATA: classroom examples; these are not physical-rover measurements")
    print(f"SAMPLES: {SAMPLES}\n")

    history = train(
        start_weight=args.start_weight,
        learning_rate=args.learning_rate,
        steps=args.steps,
    )
    for step in history:
        print(f"STEP {step.number}")
        print(f"  weight before : {step.weight_before:9.4f}")
        print(f"  predictions   : {values(step.predictions)}")
        print(f"  errors        : {values(step.errors)}")
        print(f"  mean sq. loss : {step.loss:9.4f}")
        print(f"  gradient      : {step.gradient:9.4f}")
        print(
            "  weight change : "
            f"-{args.learning_rate:.3f} * {step.gradient:.4f} "
            f"= {step.weight_change:+.4f}"
        )
        print(f"  weight after  : {step.weight_after:9.4f}\n")

    final_weight = history[-1].weight_after if history else args.start_weight
    print(
        "LEARNED RULE: predicted_turn_rate = "
        f"{final_weight:.4f} * pwm_command"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
