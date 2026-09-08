#!/usr/bin/env python3
"""Minimal MuJoCo adapter using the rover's normalized action interface."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

import mujoco
import numpy


MODEL_PATH = Path(__file__).resolve().parents[2] / "simulation" / "frontier_rover.xml"


@dataclass(frozen=True)
class SimObservation:
    time_s: float
    x_m: float
    y_m: float
    heading_rad: float
    forward_velocity_mps: float
    yaw_rate_rps: float


@dataclass(frozen=True)
class DynamicsParameters:
    floor_friction: float = 1.0
    left_turn_gain: float = 0.90
    right_turn_gain: float = 0.84
    velocity_feedback: float = 0.004
    left_drive_scale: float = 1.0
    right_drive_scale: float = 1.0


def action_to_tank(forward: float, turn: float) -> tuple[float, float]:
    """Mix normalized forward/right-turn commands into left/right commands."""
    if not -1.0 <= forward <= 1.0 or not -1.0 <= turn <= 1.0:
        raise ValueError("forward and turn must be between -1 and 1")
    left = forward + turn
    right = forward - turn
    scale = max(1.0, abs(left), abs(right))
    return left / scale, right / scale


class RoverSimulation:
    def __init__(
        self,
        model_path: Path = MODEL_PATH,
        parameters: DynamicsParameters | None = None,
        *,
        model_xml: str | None = None,
    ) -> None:
        self.model = (
            mujoco.MjModel.from_xml_string(model_xml)
            if model_xml is not None
            else mujoco.MjModel.from_xml_path(str(model_path))
        )
        self.parameters = parameters or DynamicsParameters()
        self.apply_dynamics(self.parameters)
        self.data = mujoco.MjData(self.model)
        self.reset()

    def reset(self) -> SimObservation:
        mujoco.mj_resetData(self.model, self.data)
        mujoco.mj_forward(self.model, self.data)
        return self.observe()

    def apply_dynamics(self, parameters: DynamicsParameters) -> None:
        if not 0.1 <= parameters.floor_friction <= 2.0:
            raise ValueError("floor friction must be between 0.1 and 2.0")
        if any(
            not 0.05 <= value <= 2.0
            for value in (parameters.left_turn_gain, parameters.right_turn_gain)
        ):
            raise ValueError("turn gains must be between 0.05 and 2.0")
        if not 0.0 <= parameters.velocity_feedback <= 0.1:
            raise ValueError("velocity feedback must be between 0 and 0.1")
        if any(
            not 0.5 <= value <= 1.5
            for value in (parameters.left_drive_scale, parameters.right_drive_scale)
        ):
            raise ValueError("drive scales must be between 0.5 and 1.5")
        self.parameters = parameters
        floor_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_GEOM, "floor")
        self.model.geom_friction[floor_id, 0] = parameters.floor_friction
        self.model.actuator_gear[:, 0] = 1.0
        self.model.actuator_gainprm[:, 0] = (
            parameters.left_turn_gain + parameters.right_turn_gain
        ) * 0.5
        self.model.actuator_biasprm[:, 2] = -parameters.velocity_feedback

    def set_action(self, forward: float, turn: float) -> None:
        left, right = action_to_tank(forward, turn)
        if turn < 0.0:
            gain = self.parameters.left_turn_gain
        elif turn > 0.0:
            gain = self.parameters.right_turn_gain
        else:
            gain = (
                self.parameters.left_turn_gain + self.parameters.right_turn_gain
            ) * 0.5
        self.model.actuator_gainprm[:, 0] = gain
        left *= self.parameters.left_drive_scale
        right *= self.parameters.right_drive_scale
        self.data.ctrl[:] = numpy.clip((left, left, right, right), -1.0, 1.0)

    def step(self, forward: float, turn: float, duration_s: float) -> SimObservation:
        if duration_s < 0:
            raise ValueError("duration_s must not be negative")
        self.set_action(forward, turn)
        target_time = self.data.time + duration_s
        while self.data.time < target_time:
            mujoco.mj_step(self.model, self.data)
        return self.observe()

    def set_planar_state(self, x_m: float, y_m: float, heading_rad: float) -> None:
        """Place the free chassis on the floor and clear accumulated velocity."""
        self.data.qpos[0:3] = (x_m, y_m, 0.065)
        self.data.qpos[3:7] = (
            math.cos(heading_rad * 0.5),
            0.0,
            0.0,
            math.sin(heading_rad * 0.5),
        )
        self.data.qvel[:] = 0.0
        mujoco.mj_forward(self.model, self.data)

    def observe(self) -> SimObservation:
        position = self.data.sensor("position").data
        quaternion = self.data.sensor("orientation").data
        rotation = numpy.zeros(9, dtype=numpy.float64)
        mujoco.mju_quat2Mat(rotation, quaternion)
        heading = math.atan2(rotation[3], rotation[0])
        velocity = self.data.qvel[0:3]
        forward_velocity = math.cos(heading) * velocity[0] + math.sin(heading) * velocity[1]
        yaw_rate = self.data.sensor("yaw_rate_sensor").data[2]
        return SimObservation(
            time_s=float(self.data.time),
            x_m=float(position[0]),
            y_m=float(position[1]),
            heading_rad=float(heading),
            forward_velocity_mps=float(forward_velocity),
            yaw_rate_rps=float(yaw_rate),
        )
