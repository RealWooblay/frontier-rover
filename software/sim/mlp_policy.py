#!/usr/bin/env python3
"""Small NumPy neural policy with inspectable training and inference."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy

from navigation_env import NavigationAction, NavigationObservation


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
OUTPUT_NAMES = ("forward", "turn")


@dataclass
class TrainingHistory:
    train_loss: list[float]
    validation_loss: list[float]


class TinyMLP:
    def __init__(self, hidden_size: int = 32, seed: int = 7) -> None:
        rng = numpy.random.default_rng(seed)
        self.w1 = rng.normal(0.0, (2.0 / len(INPUT_NAMES)) ** 0.5, (len(INPUT_NAMES), hidden_size))
        self.b1 = numpy.zeros(hidden_size)
        self.w2 = rng.normal(0.0, (2.0 / hidden_size) ** 0.5, (hidden_size, len(OUTPUT_NAMES)))
        self.b2 = numpy.zeros(len(OUTPUT_NAMES))

    @property
    def parameters(self) -> dict[str, numpy.ndarray]:
        return {"w1": self.w1, "b1": self.b1, "w2": self.w2, "b2": self.b2}

    def forward(self, inputs: numpy.ndarray) -> tuple[numpy.ndarray, numpy.ndarray]:
        hidden = numpy.tanh(inputs @ self.w1 + self.b1)
        output = numpy.tanh(hidden @ self.w2 + self.b2)
        return hidden, output

    def predict(self, inputs: numpy.ndarray) -> numpy.ndarray:
        return self.forward(numpy.asarray(inputs, dtype=numpy.float64))[1]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        numpy.savez_compressed(path, **self.parameters)

    @classmethod
    def load(cls, path: Path) -> "TinyMLP":
        values = numpy.load(path)
        model = cls(hidden_size=int(values["b1"].shape[0]))
        for name, parameter in model.parameters.items():
            parameter[:] = values[name]
        return model

    def fit(
        self,
        train_x: numpy.ndarray,
        train_y: numpy.ndarray,
        validation_x: numpy.ndarray,
        validation_y: numpy.ndarray,
        *,
        epochs: int = 220,
        batch_size: int = 256,
        learning_rate: float = 0.003,
        seed: int = 7,
        turn_loss_weight: float = 4.0,
    ) -> TrainingHistory:
        rng = numpy.random.default_rng(seed)
        first_moment = {name: numpy.zeros_like(value) for name, value in self.parameters.items()}
        second_moment = {name: numpy.zeros_like(value) for name, value in self.parameters.items()}
        beta1 = 0.9
        beta2 = 0.999
        epsilon = 1e-8
        step = 0
        history = TrainingHistory([], [])

        for _epoch in range(epochs):
            order = rng.permutation(len(train_x))
            for start in range(0, len(order), batch_size):
                indices = order[start : start + batch_size]
                inputs = train_x[indices]
                targets = train_y[indices]
                hidden, output = self.forward(inputs)
                weights = numpy.asarray((1.0, turn_loss_weight))
                output_gradient = (
                    2.0
                    * (output - targets)
                    * weights
                    / (len(indices) * weights.sum())
                )
                output_pre_gradient = output_gradient * (1.0 - output * output)
                gradients = {
                    "w2": hidden.T @ output_pre_gradient,
                    "b2": output_pre_gradient.sum(axis=0),
                }
                hidden_gradient = output_pre_gradient @ self.w2.T
                hidden_pre_gradient = hidden_gradient * (1.0 - hidden * hidden)
                gradients["w1"] = inputs.T @ hidden_pre_gradient
                gradients["b1"] = hidden_pre_gradient.sum(axis=0)

                step += 1
                for name, parameter in self.parameters.items():
                    gradient = gradients[name]
                    first_moment[name] = beta1 * first_moment[name] + (1.0 - beta1) * gradient
                    second_moment[name] = beta2 * second_moment[name] + (1.0 - beta2) * gradient * gradient
                    corrected_first = first_moment[name] / (1.0 - beta1**step)
                    corrected_second = second_moment[name] / (1.0 - beta2**step)
                    parameter -= learning_rate * corrected_first / (
                        numpy.sqrt(corrected_second) + epsilon
                    )

            history.train_loss.append(mean_squared_error(self.predict(train_x), train_y))
            history.validation_loss.append(
                mean_squared_error(self.predict(validation_x), validation_y)
            )
        return history


class SafetyShield:
    """Observation-only collision guard shared by learned and expert policies."""

    def __init__(self) -> None:
        self.reverse_steps = 0
        self.pivot_steps = 0
        self.escape_turn = 0.0
        self.hazard_latched = False
        self.clear_steps = 0

    def reset(self) -> None:
        self.reverse_steps = 0
        self.pivot_steps = 0
        self.escape_turn = 0.0
        self.hazard_latched = False
        self.clear_steps = 0

    @staticmethod
    def _turn_toward_free_space(observation: NavigationObservation) -> float:
        # Positive action turns right; larger left clearance therefore means turn left.
        return -0.22 if observation.left_clearance > observation.right_clearance else 0.22

    def apply(
        self,
        observation: NavigationObservation,
        proposed: NavigationAction,
    ) -> NavigationAction:
        hazard = observation.collision > 0.5 or observation.stuck > 0.5
        if hazard and not self.hazard_latched:
            self.hazard_latched = True
            self.clear_steps = 0
            self.reverse_steps = 10 if observation.collision > 0.5 else 0
            self.pivot_steps = 18
            self.escape_turn = self._turn_toward_free_space(observation)
        elif not hazard:
            self.clear_steps += 1
            if self.clear_steps >= 5:
                self.hazard_latched = False
        else:
            self.clear_steps = 0

        if (
            observation.front_clearance < 0.16
            and self.reverse_steps == 0
            and self.pivot_steps == 0
        ):
            self.reverse_steps = 4
            self.pivot_steps = 12
            self.escape_turn = self._turn_toward_free_space(observation)
        elif observation.front_clearance < 0.31 and self.pivot_steps == 0:
            self.pivot_steps = 10
            self.escape_turn = self._turn_toward_free_space(observation)

        if self.reverse_steps > 0:
            self.reverse_steps -= 1
            return NavigationAction(-0.24, self.escape_turn * 0.45, "safety_recovery_reverse")
        if self.pivot_steps > 0:
            self.pivot_steps -= 1
            return NavigationAction(0.0, self.escape_turn, "safety_recovery_pivot")

        forward = proposed.forward
        turn = proposed.turn
        mode = proposed.mode
        if observation.left_clearance < 0.14:
            forward = min(forward, 0.20)
            turn = max(turn, 0.12)
            mode = "safety_side_right"
        if observation.right_clearance < 0.14:
            forward = min(forward, 0.20)
            turn = min(turn, -0.12)
            mode = "safety_side_left"
        if observation.front_clearance < 0.45:
            forward = min(forward, max(0.04, 0.55 * (observation.front_clearance - 0.16)))
            mode = f"safety_slow_{mode}"
        return NavigationAction(float(forward), float(turn), mode)


class ShieldedNavigationPolicy:
    """Apply the same safety boundary to any performance policy."""

    def __init__(self, policy) -> None:
        self.policy = policy
        self.shield = SafetyShield()
        self.name = f"shielded_{policy.name}"

    def reset(self) -> None:
        reset = getattr(self.policy, "reset", None)
        if callable(reset):
            reset()
        self.shield.reset()

    def act(self, observation: NavigationObservation) -> NavigationAction:
        return self.shield.apply(observation, self.policy.act(observation))


class LearnedNavigationPolicy:
    name = "learned_mlp_with_safety"

    def __init__(self, model: TinyMLP) -> None:
        self.model = model
        self.shield = SafetyShield()

    def reset(self) -> None:
        self.shield.reset()

    def act(self, observation: NavigationObservation) -> NavigationAction:
        output = self.model.predict(numpy.asarray(observation.vector()))
        forward = float(numpy.clip(output[0], -0.35, 0.65))
        turn = float(numpy.clip(output[1], -0.18, 0.18))
        mode = "learned_align" if abs(observation.goal_error) > 0.18 else "learned_track"
        return self.shield.apply(observation, NavigationAction(forward, turn, mode))


def mean_squared_error(prediction: numpy.ndarray, target: numpy.ndarray) -> float:
    return float(numpy.mean((prediction - target) ** 2))
