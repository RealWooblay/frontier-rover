#!/usr/bin/env python3
"""Gymnasium environment backed by the contact-physical Frontier Rover model."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
import base64
import math
import random
from typing import Any

import gymnasium as gym
import numpy

from grid_mapping import DeadReckoningEstimator, Pose2D, wrap_angle
from mujoco_rover import DynamicsParameters, RoverSimulation, SimObservation
from mujoco_world import GeometrySensors, build_world_xml, encode_jpeg
from navigation_env import (
    NavigationAction,
    NavigationObservation,
    NavigationPolicy,
    CircleObstacle,
)
from visual_target_scenario import VisualTarget


CONTROL_PERIOD_S = 0.05
MAX_RANGE_M = 2.2
GOAL_NORMALIZATION_M = 3.0
VELOCITY_NORMALIZATION_MPS = 0.6
YAW_NORMALIZATION_RPS = 4.0
GOAL_TOLERANCE_M = 0.20
RANGE_BEARINGS_RAD = tuple(math.radians(-100 + index * 5) for index in range(41))


@dataclass(frozen=True)
class HighFidelityScenario:
    scenario_id: int
    start_x_m: float
    start_y_m: float
    start_heading_rad: float
    goal_x_m: float
    goal_y_m: float
    obstacles: tuple[CircleObstacle, ...]
    minimum_x_m: float = -2.0
    maximum_x_m: float = 2.0
    minimum_y_m: float = -1.5
    maximum_y_m: float = 1.5

    @property
    def target(self) -> VisualTarget:
        return VisualTarget(self.goal_x_m, self.goal_y_m)

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["start_heading_degrees"] = round(math.degrees(self.start_heading_rad), 3)
        return result


@dataclass(frozen=True)
class NavigationFidelity:
    range_noise_sigma_m: float = 0.012
    range_dropout_probability: float = 0.01
    range_latency_ms: int = 40
    command_latency_ms: int = 40
    odometry_scale: float = 0.97
    odometry_noise_sigma_mps: float = 0.008
    gyro_scale: float = 1.015
    gyro_bias_dps: float = 0.10
    gyro_noise_sigma_dps: float = 0.12

    def validate(self) -> None:
        if not 0.0 <= self.range_noise_sigma_m <= 0.25:
            raise ValueError("range noise must be between 0 and 0.25 m")
        if not 0.0 <= self.range_dropout_probability <= 0.5:
            raise ValueError("range dropout must be between 0 and 0.5")
        if not 0 <= self.range_latency_ms <= 1000:
            raise ValueError("range latency must be between 0 and 1000 ms")
        if not 0 <= self.command_latency_ms <= 1000:
            raise ValueError("command latency must be between 0 and 1000 ms")
        if not 0.75 <= self.odometry_scale <= 1.25:
            raise ValueError("odometry scale must be between 0.75 and 1.25")
        if not 0.75 <= self.gyro_scale <= 1.25:
            raise ValueError("gyro scale must be between 0.75 and 1.25")


def default_scenario() -> HighFidelityScenario:
    return HighFidelityScenario(
        scenario_id=0,
        start_x_m=-1.35,
        start_y_m=-0.85,
        start_heading_rad=math.radians(12.0),
        goal_x_m=1.30,
        goal_y_m=0.82,
        obstacles=(
            CircleObstacle(-0.15, 0.12, 0.25),
            CircleObstacle(0.72, -0.38, 0.22),
        ),
    )


def generate_scenarios(count: int, seed: int) -> list[HighFidelityScenario]:
    """Create deterministic train/evaluation worlds without overlapping geometry."""
    if count < 1:
        raise ValueError("count must be positive")
    rng = random.Random(seed)
    result: list[HighFidelityScenario] = []
    for scenario_id in range(count):
        start_x = rng.uniform(-1.55, -1.05)
        start_y = rng.uniform(-1.05, 1.05)
        goal_x = rng.uniform(0.85, 1.55)
        goal_y = rng.uniform(-1.05, 1.05)
        direct_heading = math.atan2(goal_y - start_y, goal_x - start_x)
        start_heading = wrap_angle(direct_heading + rng.uniform(-0.75, 0.75))
        dx = goal_x - start_x
        dy = goal_y - start_y
        length = math.hypot(dx, dy)
        normal_x = -dy / length
        normal_y = dx / length
        obstacles: list[CircleObstacle] = []
        for fraction in (rng.uniform(0.30, 0.43), rng.uniform(0.60, 0.76)):
            side = rng.choice((-1.0, 1.0))
            offset = side * rng.uniform(0.20, 0.44)
            obstacles.append(
                CircleObstacle(
                    start_x + dx * fraction + normal_x * offset,
                    start_y + dy * fraction + normal_y * offset,
                    rng.uniform(0.15, 0.25),
                )
            )
        result.append(
            HighFidelityScenario(
                scenario_id,
                start_x,
                start_y,
                start_heading,
                goal_x,
                goal_y,
                tuple(obstacles),
            )
        )
    return result


def randomized_dynamics(seed: int) -> DynamicsParameters:
    rng = random.Random(seed)
    return DynamicsParameters(
        floor_friction=rng.uniform(0.72, 1.28),
        left_turn_gain=rng.uniform(0.82, 0.98),
        right_turn_gain=rng.uniform(0.76, 0.94),
        velocity_feedback=rng.uniform(0.0032, 0.0065),
        left_drive_scale=rng.uniform(0.90, 1.10),
        right_drive_scale=rng.uniform(0.90, 1.10),
    )


def randomized_fidelity(seed: int) -> NavigationFidelity:
    rng = random.Random(seed)
    return NavigationFidelity(
        range_noise_sigma_m=rng.uniform(0.004, 0.035),
        range_dropout_probability=rng.uniform(0.0, 0.045),
        range_latency_ms=rng.randrange(0, 121, 10),
        command_latency_ms=rng.randrange(0, 101, 10),
        odometry_scale=rng.uniform(0.93, 1.07),
        odometry_noise_sigma_mps=rng.uniform(0.002, 0.018),
        gyro_scale=rng.uniform(0.97, 1.04),
        gyro_bias_dps=rng.uniform(-0.35, 0.35),
        gyro_noise_sigma_dps=rng.uniform(0.04, 0.28),
    )


class FrontierRoverEnv(gym.Env[numpy.ndarray, numpy.ndarray]):
    """One policy step advances real MuJoCo contacts and imperfect sensors."""

    metadata = {"render_modes": ["rgb_array", "onboard_rgb"], "render_fps": 20}

    def __init__(
        self,
        scenario: HighFidelityScenario | None = None,
        *,
        dynamics: DynamicsParameters | None = None,
        fidelity: NavigationFidelity | None = None,
        max_duration_s: float = 24.0,
        render_mode: str | None = None,
        forced_stuck_window: tuple[float, float] | None = None,
    ) -> None:
        super().__init__()
        if render_mode not in (None, *self.metadata["render_modes"]):
            raise ValueError(f"unsupported render mode: {render_mode}")
        self.fixed_scenario = scenario
        self.fixed_dynamics = dynamics
        self.fidelity = fidelity or NavigationFidelity()
        self.fidelity.validate()
        self.max_duration_s = max_duration_s
        self.render_mode = render_mode
        self.forced_stuck_window = forced_stuck_window
        self.action_space = gym.spaces.Box(-1.0, 1.0, shape=(2,), dtype=numpy.float32)
        self.observation_space = gym.spaces.Box(-1.0, 1.0, shape=(9,), dtype=numpy.float32)
        self.simulation: RoverSimulation | None = None
        self.sensors: GeometrySensors | None = None
        self.scenario = scenario or default_scenario()
        self.dynamics = dynamics or DynamicsParameters()
        self.rng = random.Random(0)
        self.estimator = DeadReckoningEstimator()
        self.estimate = self.estimator.estimate()
        self.range_queue: deque[tuple[float, list[float]]] = deque()
        self.command_queue: deque[tuple[float, numpy.ndarray]] = deque()
        self.delivered_ranges = [MAX_RANGE_M] * len(RANGE_BEARINGS_RAD)
        self.delivered_speed_mps = 0.0
        self.delivered_yaw_rate_rps = 0.0
        self.applied_action = numpy.zeros(2, dtype=numpy.float32)
        self.executed_action = numpy.zeros(2, dtype=numpy.float32)
        self.last_requested_action = numpy.zeros(2, dtype=numpy.float32)
        self.last_true_distance_m = math.inf
        self.last_position = (0.0, 0.0)
        self.no_progress_steps = 0
        self.contact_active = False
        self.contact_episodes = 0
        self.range_dropouts = 0
        self.path_length_m = 0.0
        self.steps = 0
        self.last_observation = NavigationObservation(1.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0)

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[numpy.ndarray, dict[str, object]]:
        super().reset(seed=seed)
        actual_seed = 0 if seed is None else seed
        self.rng = random.Random(actual_seed)
        self.close()
        if self.fixed_scenario is None:
            self.scenario = generate_scenarios(1, actual_seed)[0]
        else:
            self.scenario = self.fixed_scenario
        self.dynamics = self.fixed_dynamics or randomized_dynamics(actual_seed + 10_000)
        self.simulation = RoverSimulation(
            parameters=self.dynamics,
            model_xml=build_world_xml(self.scenario),
        )
        self.simulation.set_planar_state(
            self.scenario.start_x_m,
            self.scenario.start_y_m,
            self.scenario.start_heading_rad,
        )
        self.sensors = GeometrySensors(self.simulation.model, self.simulation.data)
        if self.render_mode is not None:
            self.sensors.open_renderer(width=640, height=360)
        self.estimator = DeadReckoningEstimator(
            Pose2D(
                self.scenario.start_x_m,
                self.scenario.start_y_m,
                self.scenario.start_heading_rad,
            )
        )
        self.estimate = self.estimator.estimate()
        self.range_queue.clear()
        self.command_queue.clear()
        self.delivered_ranges = [MAX_RANGE_M] * len(RANGE_BEARINGS_RAD)
        self.delivered_speed_mps = 0.0
        self.delivered_yaw_rate_rps = 0.0
        self.applied_action = numpy.zeros(2, dtype=numpy.float32)
        self.executed_action = numpy.zeros(2, dtype=numpy.float32)
        self.last_requested_action = numpy.zeros(2, dtype=numpy.float32)
        rover = self.simulation.observe()
        self.last_true_distance_m = self._true_goal_distance(rover)
        self.last_position = (rover.x_m, rover.y_m)
        self.no_progress_steps = 0
        self.contact_active = False
        self.contact_episodes = 0
        self.range_dropouts = 0
        self.path_length_m = 0.0
        self.steps = 0
        self._sample_and_deliver_sensors(rover)
        self.last_observation = self._navigation_observation(rover, False, False)
        return self._vector(self.last_observation), self._info(rover, {}, False)

    def step(
        self, action: numpy.ndarray
    ) -> tuple[numpy.ndarray, float, bool, bool, dict[str, object]]:
        if self.simulation is None or self.sensors is None:
            raise RuntimeError("reset must be called before step")
        requested = numpy.asarray(action, dtype=numpy.float32)
        if requested.shape != (2,) or not numpy.isfinite(requested).all():
            raise ValueError("action must be a finite [forward, turn] vector")
        requested = numpy.clip(requested, -1.0, 1.0)
        now = self.simulation.data.time
        self.command_queue.append((now, requested.copy()))
        cutoff = now - self.fidelity.command_latency_ms / 1000.0
        while self.command_queue and self.command_queue[0][0] <= cutoff + 1e-9:
            _stamp, self.applied_action = self.command_queue.popleft()
        forced_stuck = bool(
            self.forced_stuck_window
            and self.forced_stuck_window[0] <= now < self.forced_stuck_window[1]
        )
        applied = numpy.zeros(2, dtype=numpy.float32) if forced_stuck else self.applied_action
        self.executed_action = applied.copy()
        before = self.simulation.observe()
        rover = self.simulation.step(float(applied[0]), float(applied[1]), CONTROL_PERIOD_S)
        travelled = math.hypot(rover.x_m - before.x_m, rover.y_m - before.y_m)
        self.path_length_m += travelled
        self._sample_and_deliver_sensors(rover)
        contacts = self.sensors.contacts()
        collision = bool(contacts)
        if collision and not self.contact_active:
            self.contact_episodes += 1
        self.contact_active = collision
        if abs(float(requested[0])) > 0.15 and travelled < 0.0008:
            self.no_progress_steps += 1
        else:
            self.no_progress_steps = 0
        stuck = forced_stuck or self.no_progress_steps >= 10
        observation = self._navigation_observation(rover, collision, stuck)
        true_distance = self._true_goal_distance(rover)
        progress = self.last_true_distance_m - true_distance
        success = true_distance <= GOAL_TOLERANCE_M
        reward_terms = {
            "progress": 7.0 * progress,
            "time": -0.01,
            "contact": -1.2 if collision else 0.0,
            "control": -0.012 * abs(float(requested[1])),
            "success": 10.0 if success else 0.0,
        }
        reward = float(sum(reward_terms.values()))
        self.last_true_distance_m = true_distance
        self.last_position = (rover.x_m, rover.y_m)
        self.last_requested_action = requested
        self.last_observation = observation
        self.steps += 1
        terminated = success
        truncated = rover.time_s >= self.max_duration_s
        return (
            self._vector(observation),
            reward,
            terminated,
            truncated,
            self._info(rover, reward_terms, forced_stuck),
        )

    def _sample_and_deliver_sensors(self, rover: SimObservation) -> None:
        assert self.sensors is not None
        ideal = self.sensors.ranges(rover.heading_rad, list(RANGE_BEARINGS_RAD), MAX_RANGE_M)
        noisy: list[float] = []
        for distance in ideal:
            if self.rng.random() < self.fidelity.range_dropout_probability:
                noisy.append(MAX_RANGE_M)
                self.range_dropouts += 1
            elif distance >= MAX_RANGE_M:
                noisy.append(MAX_RANGE_M)
            else:
                noisy.append(
                    max(
                        0.02,
                        min(
                            MAX_RANGE_M,
                            distance + self.rng.gauss(0.0, self.fidelity.range_noise_sigma_m),
                        ),
                    )
                )
        self.range_queue.append((rover.time_s, noisy))
        cutoff = rover.time_s - self.fidelity.range_latency_ms / 1000.0
        while self.range_queue and self.range_queue[0][0] <= cutoff + 1e-9:
            _stamp, self.delivered_ranges = self.range_queue.popleft()
        speed = (
            rover.forward_velocity_mps * self.fidelity.odometry_scale
            + self.rng.gauss(0.0, self.fidelity.odometry_noise_sigma_mps)
        )
        yaw_rate = (
            rover.yaw_rate_rps * self.fidelity.gyro_scale
            + math.radians(self.fidelity.gyro_bias_dps)
            + math.radians(self.rng.gauss(0.0, self.fidelity.gyro_noise_sigma_dps))
        )
        self.delivered_speed_mps = speed
        self.delivered_yaw_rate_rps = yaw_rate
        self.estimate = self.estimator.update(speed, yaw_rate, CONTROL_PERIOD_S)

    def _navigation_observation(
        self,
        rover: SimObservation,
        collision: bool,
        stuck: bool,
    ) -> NavigationObservation:
        pose = self.estimate.pose
        dx = self.scenario.goal_x_m - pose.x_m
        dy = self.scenario.goal_y_m - pose.y_m
        bearing = wrap_angle(math.atan2(dy, dx) - pose.heading_rad)
        ranges = self.delivered_ranges

        def sector(minimum_degrees: float, maximum_degrees: float) -> float:
            values = [
                value
                for value, angle in zip(ranges, RANGE_BEARINGS_RAD)
                if minimum_degrees <= math.degrees(angle) <= maximum_degrees
            ]
            return min(values, default=MAX_RANGE_M) / MAX_RANGE_M

        return NavigationObservation(
            goal_distance=max(0.0, min(1.0, math.hypot(dx, dy) / GOAL_NORMALIZATION_M)),
            goal_error=max(-1.0, min(1.0, -bearing / math.pi)),
            front_clearance=sector(-20.0, 20.0),
            left_clearance=sector(25.0, 70.0),
            right_clearance=sector(-70.0, -25.0),
            forward_velocity=max(
                -1.0, min(1.0, self.delivered_speed_mps / VELOCITY_NORMALIZATION_MPS)
            ),
            yaw_rate=max(
                -1.0, min(1.0, self.delivered_yaw_rate_rps / YAW_NORMALIZATION_RPS)
            ),
            collision=1.0 if collision else 0.0,
            stuck=1.0 if stuck else 0.0,
        )

    @staticmethod
    def _vector(observation: NavigationObservation) -> numpy.ndarray:
        return numpy.asarray(observation.vector(), dtype=numpy.float32)

    def _true_goal_distance(self, rover: SimObservation) -> float:
        return math.hypot(self.scenario.goal_x_m - rover.x_m, self.scenario.goal_y_m - rover.y_m)

    def _info(
        self,
        rover: SimObservation,
        reward_terms: dict[str, float],
        forced_stuck: bool,
    ) -> dict[str, object]:
        contacts = self.sensors.contacts() if self.sensors is not None else []
        pose = self.estimate.pose
        return {
            "time_s": round(rover.time_s, 4),
            "scenario": self.scenario.to_dict(),
            "observation": asdict(self.last_observation),
            "requested_action": self.last_requested_action.astype(float).tolist(),
            "applied_action": self.applied_action.astype(float).tolist(),
            "executed_action": self.executed_action.astype(float).tolist(),
            "ground_truth": asdict(rover),
            "estimated_pose": asdict(pose),
            "pose_error_m": round(math.hypot(pose.x_m - rover.x_m, pose.y_m - rover.y_m), 4),
            "goal_distance_m": round(self._true_goal_distance(rover), 4),
            "contacts": contacts,
            "contact_episodes": self.contact_episodes,
            "range_scan_m": [round(value, 3) for value in self.delivered_ranges],
            "range_dropouts": self.range_dropouts,
            "forced_stuck": forced_stuck,
            "reward_terms": reward_terms,
            "path_length_m": round(self.path_length_m, 4),
            "parameters": {
                "dynamics": asdict(self.dynamics),
                "fidelity": asdict(self.fidelity),
            },
            "truth_boundary": (
                "ground_truth and reward use MuJoCo state; the policy receives only the "
                "nine-element observation vector"
            ),
        }

    def render(self) -> numpy.ndarray:
        if self.sensors is None:
            raise RuntimeError("reset must be called before render")
        camera = "front_camera" if self.render_mode == "onboard_rgb" else "chase_camera"
        return self.sensors.render(camera)

    def render_pair(self) -> tuple[numpy.ndarray, numpy.ndarray]:
        if self.sensors is None:
            raise RuntimeError("reset must be called before render")
        return self.sensors.render("chase_camera"), self.sensors.render("front_camera")

    def close(self) -> None:
        if self.sensors is not None:
            self.sensors.close()
        self.sensors = None
        self.simulation = None


def run_policy_episode(
    scenario: HighFidelityScenario,
    policy: NavigationPolicy,
    *,
    dynamics: DynamicsParameters | None = None,
    fidelity: NavigationFidelity | None = None,
    seed: int = 0,
    max_duration_s: float = 24.0,
    forced_stuck_window: tuple[float, float] | None = None,
    capture_frames: bool = False,
    frame_period_s: float = 0.25,
) -> dict[str, object]:
    env = FrontierRoverEnv(
        scenario,
        dynamics=dynamics,
        fidelity=fidelity,
        max_duration_s=max_duration_s,
        render_mode="rgb_array" if capture_frames else None,
        forced_stuck_window=forced_stuck_window,
    )
    reset = getattr(policy, "reset", None)
    if callable(reset):
        reset()
    observation, info = env.reset(seed=seed)
    trace: list[dict[str, object]] = []
    frames: list[dict[str, object]] = []
    reward_total = 0.0
    recoveries = 0
    previous_mode = ""
    next_frame_s = 0.0
    terminated = False
    truncated = False
    try:
        while not (terminated or truncated):
            nav_observation = NavigationObservation(*map(float, observation))
            action = policy.act(nav_observation)
            observation, reward, terminated, truncated, info = env.step(
                numpy.asarray((action.forward, action.turn), dtype=numpy.float32)
            )
            reward_total += reward
            if "recovery" in action.mode and "recovery" not in previous_mode:
                recoveries += 1
            previous_mode = action.mode
            row = {
                "step": len(trace),
                "policy": policy.name,
                "action": asdict(action),
                "reward": round(reward, 5),
                **info,
            }
            trace.append(row)
            if capture_frames and float(info["time_s"]) + 1e-9 >= next_frame_s:
                chase, onboard = env.render_pair()
                frames.append(
                    {
                        "time_s": info["time_s"],
                        "step": row["step"],
                        "chase_jpeg_base64": base64.b64encode(encode_jpeg(chase, 74)).decode(),
                        "onboard_jpeg_base64": base64.b64encode(encode_jpeg(onboard, 74)).decode(),
                    }
                )
                next_frame_s += frame_period_s
        terminal_state = "success" if terminated else "timeout"
        return {
            "result": {
                "scenario_id": scenario.scenario_id,
                "policy": policy.name,
                "success": terminated,
                "terminal_state": terminal_state,
                "elapsed_s": info["time_s"],
                "steps": len(trace),
                "reward_total": round(reward_total, 4),
                "contact_episodes": info["contact_episodes"],
                "recoveries": recoveries,
                "path_length_m": info["path_length_m"],
                "final_goal_distance_m": info["goal_distance_m"],
                "final_pose_error_m": info["pose_error_m"],
                "range_dropouts": info["range_dropouts"],
            },
            "scenario": scenario.to_dict(),
            "trace": trace,
            "frames": frames,
            "provenance": {
                "physics": "MuJoCo rigid-body and contact solver",
                "range": "MuJoCo mj_ray with delayed noisy delivery",
                "state_estimate": "dead reckoning from imperfect speed and gyro",
                "action_contract": "normalized [forward, turn] in [-1, 1]",
                "environment_contract": "Gymnasium reset/step",
                "policy_observation": "nine normalized values; no MuJoCo truth",
            },
        }
    finally:
        env.close()
