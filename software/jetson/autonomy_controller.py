#!/usr/bin/env python3
"""Deterministic visual-target controller shared by real and simulated runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


class ControlState(str, Enum):
    TARGET_LOST = "target_lost"
    REACQUIRING = "reacquiring"
    SEARCHING = "searching"
    RECOVERING = "recovering"
    ALIGNING = "aligning"
    APPROACHING = "approaching"
    ARRIVED = "arrived"
    STALE_FRAME = "stale_frame"


@dataclass(frozen=True)
class Observation:
    target_visible: bool
    horizontal_error: float = 0.0
    area_ratio: float = 0.0
    frame_age_ms: int = 0
    bottom_edge_ratio: float = 0.0


@dataclass(frozen=True)
class Action:
    forward: float
    turn: float
    state: ControlState

    def to_dict(self) -> dict[str, float | str]:
        result = asdict(self)
        result["state"] = self.state.value
        return result


@dataclass(frozen=True)
class ControllerConfig:
    # Physical defaults measured with the current camera and drivetrain.
    target_area_ratio: float = 0.143
    area_tolerance: float = 0.007
    arrival_bottom_ratio: float = 0.92
    arrival_min_area_ratio: float = 0.03
    alignment_tolerance: float = 0.15
    turn_gain: float = 0.35
    max_forward: float = 0.7
    max_turn: float = 0.35
    search_turn: float = 0.35
    min_turn: float = 0.3
    max_frame_age_ms: int = 300


class TargetController:
    """Convert target geometry into bounded forward/turn commands.

    Positive horizontal error means the target is right of image centre.
    Positive turn therefore requests a right turn.
    """

    def __init__(self, config: ControllerConfig | None = None) -> None:
        self.config = config or ControllerConfig()
        self.search_direction = 1.0
        self.arrived = False

    def update(self, observation: Observation) -> Action:
        self._validate(observation)
        config = self.config

        if observation.frame_age_ms > config.max_frame_age_ms:
            return Action(0.0, 0.0, ControlState.STALE_FRAME)
        if self.arrived:
            return Action(0.0, 0.0, ControlState.ARRIVED)
        if not observation.target_visible:
            return Action(
                0.0,
                self.search_direction * config.search_turn,
                ControlState.SEARCHING,
            )

        if observation.horizontal_error != 0.0:
            self.search_direction = 1.0 if observation.horizontal_error > 0.0 else -1.0
        area_arrival = (
            observation.area_ratio
            >= config.target_area_ratio - config.area_tolerance
        )
        floor_edge_arrival = (
            observation.bottom_edge_ratio >= config.arrival_bottom_ratio
            and observation.area_ratio >= config.arrival_min_area_ratio
        )
        if area_arrival or floor_edge_arrival:
            self.arrived = True
            return Action(0.0, 0.0, ControlState.ARRIVED)

        turn = clamp(
            config.turn_gain * observation.horizontal_error,
            -config.max_turn,
            config.max_turn,
        )
        if abs(observation.horizontal_error) > config.alignment_tolerance:
            if abs(turn) < config.min_turn:
                turn = config.min_turn if turn > 0.0 else -config.min_turn
            return Action(0.0, turn, ControlState.ALIGNING)

        distance_error = clamp(
            (config.target_area_ratio - observation.area_ratio)
            / config.target_area_ratio,
            0.0,
            1.0,
        )
        forward = config.max_forward * distance_error
        return Action(forward, turn, ControlState.APPROACHING)

    @staticmethod
    def _validate(observation: Observation) -> None:
        if not -1.0 <= observation.horizontal_error <= 1.0:
            raise ValueError("horizontal_error must be between -1 and 1")
        if not 0.0 <= observation.area_ratio <= 1.0:
            raise ValueError("area_ratio must be between 0 and 1")
        if not 0.0 <= observation.bottom_edge_ratio <= 1.0:
            raise ValueError("bottom_edge_ratio must be between 0 and 1")
        if observation.frame_age_ms < 0:
            raise ValueError("frame_age_ms must not be negative")
