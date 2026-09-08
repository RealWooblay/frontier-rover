#!/usr/bin/env python3
"""Closed-loop visual-target scenarios shared with the physical rover controller."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import Path
import sys


JETSON_PATH = Path(__file__).resolve().parents[1] / "jetson"
if str(JETSON_PATH) not in sys.path:
    sys.path.insert(0, str(JETSON_PATH))

from autonomy_controller import (  # noqa: E402
    ControlState,
    ControllerConfig,
    Observation,
    TargetController,
)
from mission_runtime import (  # noqa: E402
    ExecutionKind,
    RuntimeConfig,
    SearchProgress,
    plan_execution,
)
from mujoco_rover import DynamicsParameters, RoverSimulation, SimObservation  # noqa: E402


def wrap_angle(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


@dataclass(frozen=True)
class VisualTarget:
    x_m: float
    y_m: float
    horizontal_fov_rad: float = math.radians(70.0)
    # Two-point empirical fit: area=0.0357 at 1.0 m and 0.1359 at 0.2 m.
    area_numerator: float = 0.0962
    distance_offset_m: float = 0.641


@dataclass(frozen=True)
class ScenarioResult:
    success: bool
    terminal_state: str
    elapsed_s: float
    final_distance_m: float
    final_horizontal_error: float
    steps: int
    dynamics: DynamicsParameters
    target: VisualTarget

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        return result


def target_observation(rover: SimObservation, target: VisualTarget) -> Observation:
    dx = target.x_m - rover.x_m
    dy = target.y_m - rover.y_m
    distance = math.hypot(dx, dy)
    bearing = wrap_angle(math.atan2(dy, dx) - rover.heading_rad)
    visible = distance > 0.0 and abs(bearing) <= target.horizontal_fov_rad / 2.0
    horizontal_error = max(
        -1.0,
        min(1.0, -bearing / (target.horizontal_fov_rad / 2.0)),
    )
    effective_distance = max(distance + target.distance_offset_m, 1e-9)
    area_ratio = min(1.0, target.area_numerator / (effective_distance * effective_distance))
    return Observation(
        target_visible=visible,
        horizontal_error=horizontal_error if visible else 0.0,
        area_ratio=area_ratio if visible else 0.0,
        frame_age_ms=0,
    )


def run_scenario(
    target: VisualTarget,
    dynamics: DynamicsParameters = DynamicsParameters(),
    duration_s: float = 12.0,
    control_period_s: float = 0.05,
    trace: list[dict[str, object]] | None = None,
    controller_config: ControllerConfig | None = None,
    runtime_config: RuntimeConfig | None = None,
) -> ScenarioResult:
    if duration_s <= 0.0 or control_period_s <= 0.0:
        raise ValueError("scenario duration and control period must be positive")
    simulation = RoverSimulation()
    simulation.apply_dynamics(dynamics)
    rover = simulation.reset()
    runtime = runtime_config or RuntimeConfig()
    controller = TargetController(controller_config or runtime.controller_config())
    progress = SearchProgress()
    observation = target_observation(rover, target)
    action = controller.update(observation)
    steps = 0

    while rover.time_s < duration_s and action.state != ControlState.ARRIVED:
        command = plan_execution(action, observation, runtime, progress)
        if command.kind == ExecutionKind.FAULT:
            action = command.action
            break
        if trace is not None:
            trace.append(
                {
                    "time_s": round(rover.time_s, 4),
                    "observation": asdict(observation),
                    "action": action.to_dict(),
                    "command": command.to_dict(),
                    "rover": asdict(rover),
                }
            )
        if command.kind == ExecutionKind.HEADING_TURN:
            target_heading = wrap_angle(
                rover.heading_rad + math.radians(command.heading_degrees)
            )
            deadline = rover.time_s + 3.0
            while rover.time_s < deadline:
                error = wrap_angle(target_heading - rover.heading_rad)
                if abs(math.degrees(error)) <= 1.5:
                    break
                # Positive command turns clockwise; positive heading is CCW.
                turn = -math.copysign(runtime.search_turn, error)
                rover = simulation.step(0.0, turn, min(0.01, control_period_s))
            rover = simulation.step(0.0, 0.0, control_period_s)
        elif command.kind == ExecutionKind.MOTOR_PULSE:
            rover = simulation.step(
                action.forward,
                action.turn,
                max(command.duration_ms / 1000.0, float(simulation.model.opt.timestep)),
            )
            rover = simulation.step(0.0, 0.0, control_period_s)
        else:
            rover = simulation.step(0.0, 0.0, control_period_s)
        progress = command.progress
        if command.flip_search_direction:
            controller.search_direction *= -1.0
        observation = target_observation(rover, target)
        action = controller.update(observation)
        steps += 1
        if action.state in (ControlState.TARGET_LOST, ControlState.STALE_FRAME):
            break

    distance = math.hypot(target.x_m - rover.x_m, target.y_m - rover.y_m)
    return ScenarioResult(
        success=action.state == ControlState.ARRIVED,
        terminal_state=action.state.value,
        elapsed_s=round(rover.time_s, 3),
        final_distance_m=round(distance, 4),
        final_horizontal_error=round(observation.horizontal_error, 4),
        steps=steps,
        dynamics=dynamics,
        target=target,
    )
