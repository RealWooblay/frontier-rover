#!/usr/bin/env python3
"""Shared mission command semantics for physical and simulated execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import math

from autonomy_controller import Action, ControllerConfig, ControlState, Observation


@dataclass(frozen=True)
class RuntimeConfig:
    """Parameters that define both controller decisions and their execution."""

    target: str = "orange"
    confidence: float = 0.20
    target_area_ratio: float = 0.080
    area_tolerance: float = 0.007
    arrival_bottom_ratio: float = 0.880
    arrival_min_area_ratio: float = 0.030
    close_loss_area_ratio: float = 0.065
    minimum_target_area_ratio: float = 0.005
    alignment_tolerance: float = 0.40
    turn_gain: float = 0.12
    max_forward: float = 0.70
    max_turn: float = 0.35
    search_turn: float = 0.35
    min_turn: float = 0.30
    max_frame_age_ms: int = 500
    turn_pulse_ms: int = 45
    alignment_pulse_ms: int = 35
    reacquire_hold_ms: int = 1500
    search_step_degrees: float = 30.0
    camera_half_fov_degrees: float = 33.0
    approach_pulse_ms: int = 100
    maximum_search_steps: int = 12
    recovery_reverse: float = 0.35
    recovery_reverse_ms: int = 300
    maximum_search_cycles: int = 3
    observation_frames: int = 3
    observation_interval_ms: int = 80

    def controller_config(self) -> ControllerConfig:
        return ControllerConfig(
            target_area_ratio=self.target_area_ratio,
            area_tolerance=self.area_tolerance,
            arrival_bottom_ratio=self.arrival_bottom_ratio,
            arrival_min_area_ratio=self.arrival_min_area_ratio,
            alignment_tolerance=self.alignment_tolerance,
            turn_gain=self.turn_gain,
            max_forward=self.max_forward,
            max_turn=self.max_turn,
            search_turn=self.search_turn,
            min_turn=self.min_turn,
            max_frame_age_ms=self.max_frame_age_ms,
        )


class ExecutionKind(str, Enum):
    STOP = "stop"
    HEADING_TURN = "heading_turn"
    MOTOR_PULSE = "motor_pulse"
    FAULT = "fault"


@dataclass(frozen=True)
class SearchProgress:
    steps: int = 0
    cycles: int = 0


@dataclass(frozen=True)
class MissionCommand:
    """One controller decision plus its hardware-independent execution semantics."""

    action: Action
    kind: ExecutionKind
    progress: SearchProgress
    duration_ms: int = 0
    heading_degrees: float = 0.0
    flip_search_direction: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action.to_dict(),
            "execution": self.kind.value,
            "duration_ms": self.duration_ms,
            "heading_degrees": self.heading_degrees,
            "search": asdict(self.progress),
            "flip_search_direction": self.flip_search_direction,
            "error": self.error,
        }


def plan_execution(
    action: Action,
    observation: Observation,
    config: RuntimeConfig,
    progress: SearchProgress,
) -> MissionCommand:
    """Translate a policy output into the same bounded operation on every runtime."""

    if action.state == ControlState.SEARCHING:
        if progress.steps >= config.maximum_search_steps:
            if progress.cycles >= config.maximum_search_cycles:
                return MissionCommand(
                    action=Action(0.0, 0.0, ControlState.TARGET_LOST),
                    kind=ExecutionKind.FAULT,
                    progress=progress,
                    error=(
                        f"{config.target} not found after bounded expanding search"
                    ),
                )
            recovery = Action(
                -config.recovery_reverse,
                0.0,
                ControlState.RECOVERING,
            )
            return MissionCommand(
                action=recovery,
                kind=ExecutionKind.MOTOR_PULSE,
                duration_ms=config.recovery_reverse_ms,
                progress=SearchProgress(0, progress.cycles + 1),
                flip_search_direction=True,
            )
        # Controller-positive turn means right. Pi-positive heading means left.
        heading_degrees = -math.copysign(config.search_step_degrees, action.turn)
        return MissionCommand(
            action=action,
            kind=ExecutionKind.HEADING_TURN,
            heading_degrees=heading_degrees,
            progress=SearchProgress(progress.steps + 1, progress.cycles),
        )

    if action.state == ControlState.ALIGNING:
        return MissionCommand(
            action=action,
            kind=ExecutionKind.MOTOR_PULSE,
            duration_ms=config.alignment_pulse_ms,
            progress=SearchProgress(),
        )

    if action.state == ControlState.APPROACHING:
        distance_fraction = max(
            0.0,
            min(
                1.0,
                (config.target_area_ratio - observation.area_ratio)
                / config.target_area_ratio,
            ),
        )
        return MissionCommand(
            action=action,
            kind=ExecutionKind.MOTOR_PULSE,
            duration_ms=max(50, round(config.approach_pulse_ms * distance_fraction)),
            progress=SearchProgress(),
        )

    return MissionCommand(
        action=action,
        kind=ExecutionKind.STOP,
        progress=progress,
    )
