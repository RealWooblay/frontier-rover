#!/usr/bin/env python3
"""Contact-physical mapping and hidden-target exploration in MuJoCo."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
import base64
import math
from pathlib import Path
import random
import sys


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "software/shared", ROOT / "software/jetson"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from autonomy_controller import Action, ControlState, Observation, TargetController  # noqa: E402
from grid_mapping import (  # noqa: E402
    DeadReckoningEstimator,
    OccupancyGrid,
    Pose2D,
    wrap_angle,
)
from mission_runtime import ExecutionKind, RuntimeConfig, SearchProgress, plan_execution  # noqa: E402
from mujoco_rover import DynamicsParameters, RoverSimulation, SimObservation  # noqa: E402
from mujoco_world import (  # noqa: E402
    CameraDetection,
    GeometrySensors,
    build_world_xml,
    detect_orange_target,
    encode_jpeg,
)
from navigation_env import CircleObstacle  # noqa: E402
from visual_target_scenario import VisualTarget  # noqa: E402


@dataclass(frozen=True)
class ExplorationWorld:
    minimum_x_m: float = -2.0
    maximum_x_m: float = 2.0
    minimum_y_m: float = -1.5
    maximum_y_m: float = 1.5
    obstacles: tuple[CircleObstacle, ...] = (
        CircleObstacle(-0.15, 0.20, 0.28),
        CircleObstacle(0.85, -0.45, 0.24),
    )
    target: VisualTarget = VisualTarget(1.35, 0.90)


@dataclass(frozen=True)
class FidelityParameters:
    """Explicit imperfections between ideal physics and planner observations."""

    seed: int = 17
    range_noise_sigma_m: float = 0.012
    range_dropout_probability: float = 0.01
    range_latency_ms: int = 40
    camera_period_ms: int = 100
    camera_latency_ms: int = 80
    camera_dropout_probability: float = 0.02
    command_latency_ms: int = 40
    odometry_noise_sigma_mps: float = 0.008
    gyro_noise_sigma_dps: float = 0.12
    rendered_camera: bool = False

    def validate(self) -> None:
        if not 0.0 <= self.range_noise_sigma_m <= 0.25:
            raise ValueError("range noise must be between 0 and 0.25 m")
        if not 0.0 <= self.odometry_noise_sigma_mps <= 0.25:
            raise ValueError("odometry noise must be between 0 and 0.25 m/s")
        if not 0.0 <= self.gyro_noise_sigma_dps <= 10.0:
            raise ValueError("gyro noise must be between 0 and 10 deg/s")
        for name, value in (
            ("range dropout", self.range_dropout_probability),
            ("camera dropout", self.camera_dropout_probability),
        ):
            if not 0.0 <= value <= 0.5:
                raise ValueError(f"{name} must be between 0 and 0.5")
        for name, value in (
            ("range latency", self.range_latency_ms),
            ("camera period", self.camera_period_ms),
            ("camera latency", self.camera_latency_ms),
            ("command latency", self.command_latency_ms),
        ):
            if not 0 <= value <= 1000:
                raise ValueError(f"{name} must be between 0 and 1000 ms")
        if self.camera_period_ms <= 0:
            raise ValueError("camera period must be positive")


def _geometric_target_observation(
    rover: SimObservation,
    target: VisualTarget,
    world: ExplorationWorld,
) -> tuple[Observation, CameraDetection]:
    """Fast non-rendering sensor used by unit tests and bulk randomization."""
    dx = target.x_m - rover.x_m
    dy = target.y_m - rover.y_m
    distance = math.hypot(dx, dy)
    relative = wrap_angle(math.atan2(dy, dx) - rover.heading_rad)
    visible = abs(relative) <= target.horizontal_fov_rad / 2.0
    if visible:
        direction_x = math.cos(rover.heading_rad + relative)
        direction_y = math.sin(rover.heading_rad + relative)
        for obstacle in world.obstacles:
            offset_x = rover.x_m - obstacle.x_m
            offset_y = rover.y_m - obstacle.y_m
            projection = offset_x * direction_x + offset_y * direction_y
            discriminant = projection * projection - (
                offset_x * offset_x
                + offset_y * offset_y
                - obstacle.radius_m * obstacle.radius_m
            )
            if discriminant >= 0.0:
                hit = -projection - math.sqrt(discriminant)
                if 0.0 <= hit < distance:
                    visible = False
                    break
    area = target.area_numerator / max((distance + target.distance_offset_m) ** 2, 1e-9)
    horizontal_error = max(
        -1.0,
        min(1.0, -relative / (target.horizontal_fov_rad / 2.0)),
    )
    observation = Observation(
        target_visible=visible,
        horizontal_error=horizontal_error if visible else 0.0,
        area_ratio=min(1.0, area) if visible else 0.0,
        frame_age_ms=0,
        bottom_edge_ratio=min(1.0, 0.45 + area * 4.5) if visible else 0.0,
    )
    detection = CameraDetection(
        target_visible=visible,
        horizontal_error=observation.horizontal_error,
        area_ratio=observation.area_ratio,
        bottom_edge_ratio=observation.bottom_edge_ratio,
        pixel_count=0,
        bbox_xyxy=None,
        estimated_distance_m=distance if visible else None,
    )
    return observation, detection


def _rendered_target_observation(
    detection: CameraDetection,
    target: VisualTarget,
    frame_age_ms: int,
) -> Observation:
    distance = detection.estimated_distance_m
    equivalent_area = (
        target.area_numerator / (distance + target.distance_offset_m) ** 2
        if distance is not None
        else 0.0
    )
    return Observation(
        target_visible=detection.target_visible,
        horizontal_error=detection.horizontal_error,
        area_ratio=min(1.0, equivalent_area),
        frame_age_ms=frame_age_ms,
        bottom_edge_ratio=detection.bottom_edge_ratio,
    )


def _path_action(
    estimate: Pose2D,
    path: list[tuple[float, float]],
    ranges: list[float],
    bearings: list[float],
) -> tuple[Action, list[tuple[float, float]]]:
    while path and math.hypot(path[0][0] - estimate.x_m, path[0][1] - estimate.y_m) < 0.10:
        path.pop(0)
    front = min(
        value for value, bearing in zip(ranges, bearings) if abs(math.degrees(bearing)) <= 18
    )
    if front < 0.30:
        left = min(value for value, bearing in zip(ranges, bearings) if bearing > 0.35)
        right = min(value for value, bearing in zip(ranges, bearings) if bearing < -0.35)
        return Action(0.0, -0.28 if left > right else 0.28, ControlState.ALIGNING), path
    if not path:
        return Action(0.0, 0.25, ControlState.SEARCHING), path
    lookahead = path[min(3, len(path) - 1)]
    bearing = wrap_angle(
        math.atan2(lookahead[1] - estimate.y_m, lookahead[0] - estimate.x_m)
        - estimate.heading_rad
    )
    turn = max(-0.28, min(0.28, -bearing * 0.65))
    forward = 0.32 if abs(bearing) < 0.45 else 0.05
    return Action(forward, turn, ControlState.APPROACHING), path


def _delayed(queue: deque, cutoff_s: float, fallback: object) -> tuple[float, object]:
    selected_time = -math.inf
    selected = fallback
    while queue and queue[0][0] <= cutoff_s:
        selected_time, selected = queue.popleft()
    return selected_time, selected


def _noisy_ranges(
    ideal: list[float],
    maximum_range_m: float,
    fidelity: FidelityParameters,
    rng: random.Random,
) -> tuple[list[float], int]:
    result = []
    dropouts = 0
    for value in ideal:
        if rng.random() < fidelity.range_dropout_probability:
            result.append(maximum_range_m)
            dropouts += 1
        elif value >= maximum_range_m:
            result.append(maximum_range_m)
        else:
            result.append(
                max(0.02, min(maximum_range_m, value + rng.gauss(0.0, fidelity.range_noise_sigma_m)))
            )
    return result, dropouts


def parameter_evidence(
    dynamics: DynamicsParameters,
    fidelity: FidelityParameters,
) -> list[dict[str, object]]:
    return [
        {"name": "left turn gain", "value": dynamics.left_turn_gain, "unit": "normalized", "status": "measured", "source": "physical MPU-9250 turn fit"},
        {"name": "right turn gain", "value": dynamics.right_turn_gain, "unit": "normalized", "status": "measured", "source": "physical MPU-9250 turn fit"},
        {"name": "velocity feedback", "value": dynamics.velocity_feedback, "unit": "model coefficient", "status": "measured", "source": "physical MPU-9250 turn fit"},
        {"name": "floor friction", "value": dynamics.floor_friction, "unit": "coefficient", "status": "assumed", "source": "not physically measured"},
        {"name": "left drive scale", "value": dynamics.left_drive_scale, "unit": "ratio", "status": "assumed", "source": "domain parameter"},
        {"name": "right drive scale", "value": dynamics.right_drive_scale, "unit": "ratio", "status": "assumed", "source": "domain parameter"},
        {"name": "range noise sigma", "value": fidelity.range_noise_sigma_m, "unit": "m", "status": "assumed", "source": "no physical range sensor exists"},
        {"name": "range latency", "value": fidelity.range_latency_ms, "unit": "ms", "status": "assumed", "source": "no physical range sensor exists"},
        {"name": "camera period", "value": fidelity.camera_period_ms, "unit": "ms", "status": "configured", "source": "simulated acquisition rate"},
        {"name": "camera latency", "value": fidelity.camera_latency_ms, "unit": "ms", "status": "assumed", "source": "physical pipeline not measured end-to-end"},
        {"name": "command latency", "value": fidelity.command_latency_ms, "unit": "ms", "status": "assumed", "source": "physical Pi-Jetson latency not measured"},
        {"name": "chassis mass", "value": 0.8, "unit": "kg", "status": "assumed", "source": "MuJoCo hypothesis; assembled rover not weighed"},
    ]


def run_exploration(
    *,
    world: ExplorationWorld = ExplorationWorld(),
    dynamics: DynamicsParameters = DynamicsParameters(),
    fidelity: FidelityParameters | None = None,
    duration_s: float = 45.0,
    control_period_s: float = 0.05,
    odometry_scale: float = 0.97,
    gyro_scale: float = 1.015,
    gyro_bias_dps: float = 0.10,
    trace: list[dict[str, object]] | None = None,
    camera_frames: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if not 0.75 <= odometry_scale <= 1.25:
        raise ValueError("odometry_scale must be between 0.75 and 1.25")
    if not 0.75 <= gyro_scale <= 1.25:
        raise ValueError("gyro_scale must be between 0.75 and 1.25")
    if not -5.0 <= gyro_bias_dps <= 5.0:
        raise ValueError("gyro_bias_dps must be between -5 and 5")
    fidelity = fidelity or FidelityParameters()
    fidelity.validate()
    rng = random.Random(fidelity.seed)
    simulation = RoverSimulation(
        parameters=dynamics,
        model_xml=build_world_xml(world),
    )
    simulation.set_planar_state(-1.45, -0.95, math.radians(12.0))
    rover = simulation.observe()
    sensors = GeometrySensors(simulation.model, simulation.data)
    effective_rendered_camera = fidelity.rendered_camera
    camera_backend_error: str | None = None
    if fidelity.rendered_camera:
        try:
            sensors.open_renderer()
        except Exception as error:  # MuJoCo requires an available platform GL context.
            effective_rendered_camera = False
            camera_backend_error = f"{type(error).__name__}: {error}"
    estimator = DeadReckoningEstimator(Pose2D(rover.x_m, rover.y_m, rover.heading_rad))
    grid = OccupancyGrid()
    bearings = [math.radians(-100 + index * 5) for index in range(41)]
    maximum_range_m = 2.2
    controller = TargetController(RuntimeConfig().controller_config())
    search_progress = SearchProgress()
    path_cells: list[tuple[int, int]] = []
    path_world: list[tuple[float, float]] = []
    target_memory: tuple[float, float] | None = None
    target_seen = False
    collisions = 0
    collision_active = False
    last_collision_start_s = -math.inf
    replans = 0
    step_index = 0
    desired_action = Action(0.0, 0.0, ControlState.SEARCHING)
    applied_action = desired_action
    range_queue: deque[tuple[float, list[float]]] = deque()
    camera_queue: deque[tuple[float, tuple[Observation, CameraDetection]]] = deque()
    action_queue: deque[tuple[float, Action]] = deque()
    delivered_ranges = [maximum_range_m] * len(bearings)
    delivered_camera = (
        Observation(False),
        CameraDetection(False, 0.0, 0.0, 0.0, 0, None, None),
    )
    next_camera_time_s = rover.time_s
    last_camera_capture_s = -math.inf
    last_saved_frame_s = -math.inf
    range_dropouts = 0
    camera_dropouts = 0
    camera_samples = 0
    contact_pairs: list[tuple[str, str]] = []

    try:
        while rover.time_s < duration_s:
            estimate_state = estimator.estimate()
            estimate = estimate_state.pose

            ideal_ranges = sensors.ranges(rover.heading_rad, bearings, maximum_range_m)
            noisy_ranges, dropped = _noisy_ranges(ideal_ranges, maximum_range_m, fidelity, rng)
            range_dropouts += dropped
            range_queue.append((rover.time_s, noisy_ranges))
            selected_time, selected_ranges = _delayed(
                range_queue,
                rover.time_s - fidelity.range_latency_ms / 1000.0,
                delivered_ranges,
            )
            if selected_time > -math.inf:
                delivered_ranges = selected_ranges

            if rover.time_s + 1e-9 >= next_camera_time_s:
                next_camera_time_s += fidelity.camera_period_ms / 1000.0
                camera_samples += 1
                if rng.random() < fidelity.camera_dropout_probability:
                    camera_dropouts += 1
                else:
                    if effective_rendered_camera:
                        frame = sensors.render_camera()
                        detection = detect_orange_target(frame)
                        captured_observation = _rendered_target_observation(
                            detection, world.target, 0
                        )
                        if camera_frames is not None and rover.time_s - last_saved_frame_s >= 0.45:
                            camera_frames.append(
                                {
                                    "time_s": round(rover.time_s, 3),
                                    "jpeg_base64": base64.b64encode(encode_jpeg(frame)).decode("ascii"),
                                    "detection": detection.to_dict(),
                                }
                            )
                            last_saved_frame_s = rover.time_s
                    else:
                        captured_observation, detection = _geometric_target_observation(
                            rover, world.target, world
                        )
                    last_camera_capture_s = rover.time_s
                    camera_queue.append(
                        (rover.time_s, (captured_observation, detection))
                    )
            selected_time, selected_camera = _delayed(
                camera_queue,
                rover.time_s - fidelity.camera_latency_ms / 1000.0,
                delivered_camera,
            )
            if selected_time > -math.inf:
                delivered_camera = selected_camera
            base_visual, camera_detection = delivered_camera
            frame_age_ms = (
                0
                if last_camera_capture_s == -math.inf
                else max(0, round((rover.time_s - last_camera_capture_s) * 1000.0))
            )
            visual = Observation(
                target_visible=base_visual.target_visible,
                horizontal_error=base_visual.horizontal_error,
                area_ratio=base_visual.area_ratio,
                frame_age_ms=frame_age_ms,
                bottom_edge_ratio=base_visual.bottom_edge_ratio,
            )

            # The virtual range head is 0.10 m ahead of the chassis origin.
            # Preserve that extrinsic transform when rays enter the map frame.
            sensor_pose = Pose2D(
                estimate.x_m + 0.10 * math.cos(estimate.heading_rad),
                estimate.y_m + 0.10 * math.sin(estimate.heading_rad),
                estimate.heading_rad,
            )
            grid.update_scan(sensor_pose, delivered_ranges, bearings, maximum_range_m)
            safety_range, safety_bearing = min(
                (value, bearing)
                for value, bearing in zip(delivered_ranges, bearings)
                if abs(math.degrees(bearing)) <= 100
            )
            forward_range, forward_bearing = min(
                (value, bearing)
                for value, bearing in zip(delivered_ranges, bearings)
                if abs(math.degrees(bearing)) <= 25
            )
            mode = "explore"
            command = None

            if contact_pairs:
                desired_action = Action(
                    0.0,
                    -0.25 if safety_bearing > 0.0 else 0.25,
                    ControlState.RECOVERING,
                )
                mode = "contact_recovery"
                path_world = []
            elif visual.target_visible:
                target_seen = True
                distance_estimate = camera_detection.estimated_distance_m
                if distance_estimate is None:
                    distance_estimate = max(
                        0.0,
                        math.sqrt(world.target.area_numerator / max(visual.area_ratio, 1e-9))
                        - world.target.distance_offset_m,
                    )
                relative = -visual.horizontal_error * world.target.horizontal_fov_rad / 2.0
                target_memory = (
                    estimate.x_m + distance_estimate * math.cos(estimate.heading_rad + relative),
                    estimate.y_m + distance_estimate * math.sin(estimate.heading_rad + relative),
                )
                if forward_range < 0.45:
                    desired_action = Action(
                        -0.10 if forward_range < 0.28 else 0.02,
                        0.30 if forward_bearing > 0.0 else -0.30,
                        ControlState.ALIGNING,
                    )
                    mode = "obstacle_avoid"
                else:
                    desired_action = controller.update(visual)
                    command = plan_execution(
                        desired_action, visual, RuntimeConfig(), search_progress
                    )
                    search_progress = command.progress
                    if command.flip_search_direction:
                        controller.search_direction *= -1.0
                    mode = "target_track"
                if desired_action.state == ControlState.ARRIVED:
                    if trace is not None:
                        row = _trace_row(
                            rover,
                            estimate_state,
                            desired_action,
                            applied_action,
                            mode,
                            visual,
                            camera_detection,
                            delivered_ranges,
                            target_memory,
                            path_world,
                            contact_pairs,
                        )
                        row["map_cells"] = grid.to_dict()["cells"]
                        trace.append(row)
                    break
            elif target_memory is not None:
                if math.hypot(target_memory[0] - estimate.x_m, target_memory[1] - estimate.y_m) > 0.28:
                    if step_index % 12 == 0 or not path_world:
                        current = grid.world_to_cell(estimate.x_m, estimate.y_m)
                        path_cells = grid.plan_toward_world(
                            current, target_memory[0], target_memory[1]
                        )
                        path_world = [grid.cell_to_world(cell) for cell in path_cells[1:]]
                        replans += 1
                    desired_action, path_world = _path_action(
                        estimate, path_world, delivered_ranges, bearings
                    )
                    mode = "target_memory"
                else:
                    target_memory = None
                    controller = TargetController(RuntimeConfig().controller_config())
                    desired_action = Action(0.0, 0.25, ControlState.REACQUIRING)
                    mode = "reacquire"
            else:
                current = grid.world_to_cell(estimate.x_m, estimate.y_m)
                if step_index % 20 == 0 or not path_world:
                    path_cells = grid.plan_to_frontier(current)
                    path_world = [grid.cell_to_world(cell) for cell in path_cells[1:]]
                    replans += 1
                desired_action, path_world = _path_action(
                    estimate, path_world, delivered_ranges, bearings
                )

            action_queue.append((rover.time_s, desired_action))
            selected_time, selected_action = _delayed(
                action_queue,
                rover.time_s - fidelity.command_latency_ms / 1000.0,
                applied_action,
            )
            if selected_time > -math.inf:
                applied_action = selected_action

            duration = control_period_s
            if command is not None and command.kind == ExecutionKind.MOTOR_PULSE:
                duration = max(control_period_s, command.duration_ms / 1000.0)
            rover = simulation.step(applied_action.forward, applied_action.turn, duration)
            new_contacts = sensors.contacts()
            has_contact = bool(new_contacts)
            if (
                has_contact
                and not collision_active
                and rover.time_s - last_collision_start_s >= 0.25
            ):
                collisions += 1
                last_collision_start_s = rover.time_s
            collision_active = has_contact
            contact_pairs = new_contacts

            sensed_speed = (
                rover.forward_velocity_mps * odometry_scale
                + rng.gauss(0.0, fidelity.odometry_noise_sigma_mps)
            )
            sensed_yaw = (
                rover.yaw_rate_rps * gyro_scale
                + math.radians(gyro_bias_dps)
                + math.radians(rng.gauss(0.0, fidelity.gyro_noise_sigma_dps))
            )
            estimator.update(sensed_speed, sensed_yaw, duration)
            if trace is not None and step_index % 2 == 0:
                row = _trace_row(
                    rover,
                    estimator.estimate(),
                    desired_action,
                    applied_action,
                    mode,
                    visual,
                    camera_detection,
                    delivered_ranges,
                    target_memory,
                    path_world,
                    contact_pairs,
                )
                if step_index % 10 == 0:
                    row["map_cells"] = grid.to_dict()["cells"]
                trace.append(row)
            step_index += 1
            if collisions >= 12:
                break
    finally:
        sensors.close()

    estimate_state = estimator.estimate()
    truth_error = math.hypot(
        estimate_state.pose.x_m - rover.x_m,
        estimate_state.pose.y_m - rover.y_m,
    )
    result = {
        "success": desired_action.state == ControlState.ARRIVED,
        "terminal_state": "arrived" if desired_action.state == ControlState.ARRIVED else "collision_limit" if collisions >= 12 else "timeout",
        "elapsed_s": round(rover.time_s, 3),
        "steps": step_index,
        "target_seen": target_seen,
        "collisions": collisions,
        "replans": replans,
        "final_distance_m": round(
            math.hypot(world.target.x_m - rover.x_m, world.target.y_m - rover.y_m), 3
        ),
        "pose_error_m": round(truth_error, 4),
        "estimate": estimate_state.to_dict(),
        "ground_truth": asdict(rover),
        "map": grid.to_dict(),
        "frontiers": [grid.cell_to_world(cell) for cell in grid.frontier_cells()[::4]],
        "world": {
            "bounds": [world.minimum_x_m, world.maximum_x_m, world.minimum_y_m, world.maximum_y_m],
            "obstacles": [asdict(item) for item in world.obstacles],
            "target": asdict(world.target),
        },
        "fidelity": {
            "physics": "MuJoCo wheel, floor, wall, and obstacle contacts",
            "range_backend": "MuJoCo mj_ray geometry intersections",
            "camera_backend": "MuJoCo rendered RGB plus HSV pixel detector" if effective_rendered_camera else "geometric camera approximation",
            "camera_backend_error": camera_backend_error,
            "collision_response": "MuJoCo contact solver; no teleport or snap-back",
            "parameters": parameter_evidence(dynamics, fidelity),
        },
        "sensor_health": {
            "range_beams": step_index * len(bearings),
            "range_dropouts": range_dropouts,
            "camera_samples": camera_samples,
            "camera_dropouts": camera_dropouts,
        },
        "sensor_model": {
            **asdict(fidelity),
            "effective_rendered_camera": effective_rendered_camera,
            "odometry_scale": odometry_scale,
            "gyro_scale": gyro_scale,
            "gyro_bias_dps": gyro_bias_dps,
            "planner_input": "estimated pose, delayed/noisy rays, occupancy grid, and delayed image detection",
            "ground_truth_access": "MuJoCo physics, scoring, and optional rendering only",
        },
        "camera_frames": camera_frames or [],
    }
    return result


def _trace_row(
    rover: SimObservation,
    estimate: object,
    desired_action: Action,
    applied_action: Action,
    mode: str,
    visual: Observation,
    camera_detection: CameraDetection,
    ranges: list[float],
    target_memory: tuple[float, float] | None,
    path: list[tuple[float, float]],
    contacts: list[tuple[str, str]],
) -> dict[str, object]:
    return {
        "time_s": round(rover.time_s, 3),
        "ground_truth": asdict(rover),
        "estimate": estimate.to_dict(),
        "action": desired_action.to_dict(),
        "applied_action": applied_action.to_dict(),
        "mode": mode,
        "target_observation": asdict(visual),
        "camera_detection": camera_detection.to_dict(),
        "range_scan_m": [round(value, 3) for value in ranges],
        "contacts": contacts,
        "target_memory": target_memory,
        "path": path[:30],
    }
