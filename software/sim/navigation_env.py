#!/usr/bin/env python3
"""Waypoint, obstacle, and recovery tasks around the MuJoCo rover dynamics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import random
from typing import Protocol

from mujoco_rover import DynamicsParameters, RoverSimulation, SimObservation


ROVER_RADIUS_M = 0.13
SENSOR_RANGE_M = 1.4
WAYPOINT_TOLERANCE_M = 0.18


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def wrap_angle(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


@dataclass(frozen=True)
class CircleObstacle:
    x_m: float
    y_m: float
    radius_m: float


@dataclass(frozen=True)
class NavigationScenario:
    scenario_id: int
    waypoints: tuple[tuple[float, float], ...]
    obstacles: tuple[CircleObstacle, ...]


@dataclass(frozen=True)
class NavigationObservation:
    goal_distance: float
    goal_error: float
    front_clearance: float
    left_clearance: float
    right_clearance: float
    forward_velocity: float
    yaw_rate: float
    collision: float
    stuck: float

    def vector(self) -> tuple[float, ...]:
        return tuple(asdict(self).values())


@dataclass(frozen=True)
class NavigationAction:
    forward: float
    turn: float
    mode: str


@dataclass(frozen=True)
class NavigationResult:
    scenario_id: int
    policy: str
    success: bool
    terminal_state: str
    elapsed_s: float
    waypoints_reached: int
    waypoint_count: int
    collisions: int
    recoveries: int
    path_length_m: float
    final_goal_distance_m: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class NavigationPolicy(Protocol):
    name: str

    def act(self, observation: NavigationObservation) -> NavigationAction: ...


def ray_circle_distance(
    origin_x: float,
    origin_y: float,
    ray_angle: float,
    obstacle: CircleObstacle,
) -> float | None:
    dx = math.cos(ray_angle)
    dy = math.sin(ray_angle)
    cx = obstacle.x_m - origin_x
    cy = obstacle.y_m - origin_y
    projection = cx * dx + cy * dy
    perpendicular_sq = cx * cx + cy * cy - projection * projection
    expanded_radius = obstacle.radius_m + ROVER_RADIUS_M
    if projection < 0.0 or perpendicular_sq > expanded_radius * expanded_radius:
        return None
    offset = math.sqrt(max(0.0, expanded_radius * expanded_radius - perpendicular_sq))
    return max(0.0, projection - offset)


def clearance(
    rover: SimObservation,
    obstacles: tuple[CircleObstacle, ...],
    relative_angle: float,
    cone_half_angle: float = math.radians(28.0),
) -> float:
    ray_angle = rover.heading_rad + relative_angle
    distances = []
    for obstacle in obstacles:
        dx = obstacle.x_m - rover.x_m
        dy = obstacle.y_m - rover.y_m
        bearing_error = abs(wrap_angle(math.atan2(dy, dx) - ray_angle))
        angular_radius = math.asin(
            min(1.0, (obstacle.radius_m + ROVER_RADIUS_M) / max(math.hypot(dx, dy), 1e-6))
        )
        if bearing_error <= cone_half_angle + angular_radius:
            distances.append(
                max(0.0, math.hypot(dx, dy) - obstacle.radius_m - ROVER_RADIUS_M)
            )
    return min([SENSOR_RANGE_M, *distances]) / SENSOR_RANGE_M


def touching_obstacle(
    rover: SimObservation, obstacles: tuple[CircleObstacle, ...]
) -> bool:
    return any(
        math.hypot(rover.x_m - obstacle.x_m, rover.y_m - obstacle.y_m)
        <= ROVER_RADIUS_M + obstacle.radius_m
        for obstacle in obstacles
    )


def observe_navigation(
    rover: SimObservation,
    waypoint: tuple[float, float],
    obstacles: tuple[CircleObstacle, ...],
    *,
    collision: bool = False,
    stuck: bool = False,
) -> NavigationObservation:
    dx = waypoint[0] - rover.x_m
    dy = waypoint[1] - rover.y_m
    distance = math.hypot(dx, dy)
    bearing = wrap_angle(math.atan2(dy, dx) - rover.heading_rad)
    # The physical action convention uses positive turn for clockwise/right.
    goal_error = clamp(-bearing / math.pi, -1.0, 1.0)
    return NavigationObservation(
        goal_distance=clamp(distance / 3.0, 0.0, 1.0),
        goal_error=goal_error,
        front_clearance=clearance(rover, obstacles, 0.0),
        left_clearance=clearance(rover, obstacles, math.radians(42.0)),
        right_clearance=clearance(rover, obstacles, math.radians(-42.0)),
        forward_velocity=clamp(rover.forward_velocity_mps / 0.6, -1.0, 1.0),
        yaw_rate=clamp(rover.yaw_rate_rps / 4.0, -1.0, 1.0),
        collision=1.0 if collision else 0.0,
        stuck=1.0 if stuck else 0.0,
    )


def expert_action(observation: NavigationObservation) -> NavigationAction:
    if observation.collision > 0.5 or observation.stuck > 0.5:
        turn = -0.12 if observation.left_clearance > observation.right_clearance else 0.12
        return NavigationAction(-0.24, turn, "recovery")

    if observation.front_clearance < 0.38:
        turn = -0.15 if observation.left_clearance > observation.right_clearance else 0.15
        return NavigationAction(0.06, turn, "avoid")

    turn = clamp(observation.goal_error * 0.55, -0.16, 0.16)
    if abs(observation.goal_error) > 0.18:
        return NavigationAction(0.05, turn, "align")
    speed = clamp(observation.goal_distance * 1.8, 0.18, 0.60)
    speed *= clamp(observation.front_clearance * 1.4, 0.25, 1.0)
    return NavigationAction(speed, turn, "track")


class ExpertPolicy:
    name = "deterministic_expert"

    def __init__(self) -> None:
        self.manoeuvre_steps = 0
        self.manoeuvre_turn = 0.0
        self.manoeuvre_mode = ""

    def reset(self) -> None:
        self.manoeuvre_steps = 0
        self.manoeuvre_turn = 0.0
        self.manoeuvre_mode = ""

    def act(self, observation: NavigationObservation) -> NavigationAction:
        if observation.collision > 0.5 or observation.stuck > 0.5:
            self.manoeuvre_steps = 12
            self.manoeuvre_turn = (
                -0.15
                if observation.left_clearance > observation.right_clearance
                else 0.15
            )
            self.manoeuvre_mode = "recovery"
        elif observation.front_clearance < 0.38 and self.manoeuvre_steps == 0:
            self.manoeuvre_steps = 16
            self.manoeuvre_turn = (
                -0.15
                if observation.left_clearance > observation.right_clearance
                else 0.15
            )
            self.manoeuvre_mode = "avoid"

        if self.manoeuvre_steps > 0:
            self.manoeuvre_steps -= 1
            if self.manoeuvre_mode == "recovery":
                return NavigationAction(-0.24, self.manoeuvre_turn, "recovery")
            return NavigationAction(0.08, self.manoeuvre_turn, "avoid")
        return expert_action(observation)


def generate_scenarios(count: int, seed: int) -> list[NavigationScenario]:
    if count < 1:
        raise ValueError("scenario count must be positive")
    rng = random.Random(seed)
    scenarios = []
    for scenario_id in range(count):
        first = (rng.uniform(1.0, 1.5), rng.uniform(-0.65, 0.65))
        second = (rng.uniform(2.0, 2.7), rng.uniform(-0.85, 0.85))

        def near_segment(
            start: tuple[float, float],
            end: tuple[float, float],
            fraction: float,
        ) -> CircleObstacle:
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            length = math.hypot(dx, dy)
            normal_x = -dy / length
            normal_y = dx / length
            offset = rng.choice((-1.0, 1.0)) * rng.uniform(0.12, 0.24)
            return CircleObstacle(
                start[0] + dx * fraction + normal_x * offset,
                start[1] + dy * fraction + normal_y * offset,
                rng.uniform(0.10, 0.16),
            )

        obstacles = (
            near_segment((0.0, 0.0), first, 0.45),
            near_segment(first, second, 0.50),
        )
        scenarios.append(NavigationScenario(scenario_id, (first, second), obstacles))
    return scenarios


def run_navigation_scenario(
    scenario: NavigationScenario,
    policy: NavigationPolicy,
    *,
    dynamics: DynamicsParameters | None = None,
    duration_s: float = 24.0,
    control_period_s: float = 0.05,
    trace: list[dict[str, object]] | None = None,
    forced_stuck_window: tuple[float, float] | None = None,
) -> NavigationResult:
    reset = getattr(policy, "reset", None)
    if callable(reset):
        reset()
    simulation = RoverSimulation(parameters=dynamics)
    rover = simulation.observe()
    waypoint_index = 0
    path_length = 0.0
    collisions = 0
    recoveries = 0
    collision = False
    best_distance = math.inf
    no_progress_steps = 0
    previous_mode = ""

    while rover.time_s < duration_s and waypoint_index < len(scenario.waypoints):
        waypoint = scenario.waypoints[waypoint_index]
        goal_distance = math.hypot(waypoint[0] - rover.x_m, waypoint[1] - rover.y_m)
        if goal_distance <= WAYPOINT_TOLERANCE_M:
            waypoint_index += 1
            best_distance = math.inf
            no_progress_steps = 0
            continue

        if goal_distance < best_distance - 0.01:
            best_distance = goal_distance
            no_progress_steps = 0
        else:
            no_progress_steps += 1
        fault_stuck = bool(
            forced_stuck_window
            and forced_stuck_window[0] <= rover.time_s < forced_stuck_window[1]
        )
        stuck = fault_stuck or (
            no_progress_steps >= round(4.0 / control_period_s)
            and abs(rover.forward_velocity_mps) < 0.02
            and previous_mode == "track"
        )
        observation = observe_navigation(
            rover,
            waypoint,
            scenario.obstacles,
            collision=collision,
            stuck=stuck,
        )
        action = policy.act(observation)
        if "recovery" in action.mode and "recovery" not in previous_mode:
            recoveries += 1
            no_progress_steps = 0
        previous_mode = action.mode
        before = rover
        rover = simulation.step(
            0.0 if fault_stuck else action.forward,
            0.0 if fault_stuck else action.turn,
            control_period_s,
        )
        path_length += math.hypot(rover.x_m - before.x_m, rover.y_m - before.y_m)
        collision = touching_obstacle(rover, scenario.obstacles)
        if collision:
            collisions += 1
            simulation.set_planar_state(
                before.x_m,
                before.y_m,
                before.heading_rad,
            )
            rover = simulation.observe()

        if trace is not None:
            trace.append(
                {
                    "time_s": round(rover.time_s, 4),
                    "waypoint_index": waypoint_index,
                    "rover": asdict(rover),
                    "observation": asdict(observation),
                    "action": asdict(action),
                    "collision": collision,
                    "forced_stuck": fault_stuck,
                }
            )
        if collisions >= 20:
            break

    final_waypoint = scenario.waypoints[min(waypoint_index, len(scenario.waypoints) - 1)]
    final_distance = math.hypot(
        final_waypoint[0] - rover.x_m, final_waypoint[1] - rover.y_m
    )
    success = waypoint_index == len(scenario.waypoints)
    terminal = "success" if success else "collision_limit" if collisions >= 20 else "timeout"
    return NavigationResult(
        scenario_id=scenario.scenario_id,
        policy=policy.name,
        success=success,
        terminal_state=terminal,
        elapsed_s=round(rover.time_s, 3),
        waypoints_reached=waypoint_index,
        waypoint_count=len(scenario.waypoints),
        collisions=collisions,
        recoveries=recoveries,
        path_length_m=round(path_length, 3),
        final_goal_distance_m=round(final_distance, 3),
    )
