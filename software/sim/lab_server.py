#!/usr/bin/env python3
"""Serve the interactive Frontier Rover simulation and evidence laboratory."""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
import json
import math
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

import numpy

from fit_imu_turn_dynamics import (
    TURN_PHASES,
    identify_yaw_axis,
    integrated_trace,
    phase_input,
    rows_for,
    segment_rows,
    simulated_trace,
    stationary_bias,
)
from exploration_scenario import ExplorationWorld, FidelityParameters, run_exploration
from high_fidelity_env import (
    generate_scenarios as generate_high_fidelity_scenarios,
    randomized_dynamics,
    randomized_fidelity,
    run_policy_episode,
)
from mlp_policy import INPUT_NAMES, LearnedNavigationPolicy, TinyMLP
from mujoco_rover import DynamicsParameters
from navigation_env import ExpertPolicy, generate_scenarios, run_navigation_scenario
from visual_target_scenario import VisualTarget, run_scenario as run_target_scenario


ROOT = Path(__file__).resolve().parents[2]
UI_PATH = Path(__file__).with_name("lab.html")
HIGH_FIDELITY_TRAINING_PATH = ROOT / "artifacts/models/high-fidelity-navigation-policy-training.json"
HIGH_FIDELITY_EVALUATION_PATH = ROOT / "artifacts/sim/high-fidelity-policy-evaluation.json"
HIGH_FIDELITY_POLICY_PATH = ROOT / "artifacts/models/high-fidelity-navigation-policy.npz"
TURN_FIT_PATH = ROOT / "artifacts/sim/2026-09-06-imu-turn-fit.json"
TURN_VALIDATION_PATH = ROOT / "artifacts/sim/2026-09-06-closed-loop-turn-validation.json"
PHYSICAL_TURN_PATH = ROOT / "artifacts/physical/2026-09-06-imu-motion.csv"
HIGH_FIDELITY_PATH = ROOT / "artifacts/sim/2026-09-06-high-fidelity-exploration.json"


SIM_PROVENANCE = {
    "source": "simulated",
    "engine": "MuJoCo",
    "physics_step_ms": 2.0,
    "view": "browser telemetry plus MuJoCo onboard camera frames",
    "measured": "directional yaw response fitted from physical MPU-9250 logs",
    "unmeasured": "translation speed, wheel slip, chassis mass, and room geometry",
}


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text())


def build_summary() -> dict[str, object]:
    training = read_json(HIGH_FIDELITY_TRAINING_PATH)
    training_rounds = training["history"]
    training["parameter_count"] = training["network"]["parameters"]
    training["history"] = {
        "train": [value for round_ in training_rounds for value in round_["train_loss"]],
        "validation": [
            value for round_ in training_rounds for value in round_["validation_loss"]
        ],
        "rounds": training_rounds,
    }
    evaluation = read_json(HIGH_FIDELITY_EVALUATION_PATH)
    high_fidelity = read_json(HIGH_FIDELITY_PATH) if HIGH_FIDELITY_PATH.exists() else None
    return {
        "training": training,
        "navigation": {
            "summary": evaluation["summary"],
            "fault_recovery": evaluation["fault_recovery"]["summary"],
        },
        "turn_fit": read_json(TURN_FIT_PATH),
        "turn_validation": read_json(TURN_VALIDATION_PATH),
        "high_fidelity": high_fidelity,
        "claims": [
            {
                "name": "Real2Sim dynamics",
                "state": "measured",
                "evidence": "Physical IMU fit; validation RMSE over three separate final-yaw endpoints",
            },
            {
                "name": "Domain-randomized policy",
                "state": "simulated",
                "evidence": (
                    f"{evaluation['summary']['high_fidelity_learned_mlp']['successes']}/"
                    f"{evaluation['summary']['high_fidelity_learned_mlp']['episodes']} evaluation "
                    "missions with zero contacts for MLP + safety filter; neural contribution not isolated"
                ),
            },
            {
                "name": "Physical selected-object autonomy",
                "state": "measured",
                "evidence": "Two accepted TensorRT missions; one began outside camera view",
            },
            {
                "name": "Shared physical/sim mission semantics",
                "state": "measured",
                "evidence": "Identical search-turn, pulse, recovery, and stop planner covered by parity tests",
            },
            {
                "name": "Jetson visual motion",
                "state": "measured",
                "evidence": "Physical saved-frame ORB test: 159 matches, 107 RANSAC inliers; pixel scale only",
            },
            {
                "name": "Occupancy mapping and frontier exploration",
                "state": "simulated",
                "evidence": "10/12 randomized rendered-camera missions; MuJoCo contacts/rays, delayed sensors, A*, target memory, and pose-error scoring",
            },
            {
                "name": "Physical metric mapping and obstacle avoidance",
                "state": "blocked by observation gap",
                "evidence": "Camera+IMU expose appearance and yaw; no metric range or wheel displacement sensor",
            },
            {
                "name": "Learned policy on physical rover",
                "state": "pending physical run",
                "evidence": "Artifact deployable; current rover lacks obstacle observation parity",
            },
            {
                "name": "Independent Jetson operation",
                "state": "pending cable acceptance",
                "evidence": "Service deployable; current USB link terminates at Mac",
            },
        ],
    }


def build_turn_traces() -> dict[str, object]:
    with PHYSICAL_TURN_PATH.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    bias = stationary_bias(rows)
    axis_index = identify_yaw_axis(rows, bias)
    axis = ("gx_dps", "gy_dps", "gz_dps")[axis_index]
    fit = read_json(TURN_FIT_PATH)["fit"]
    parameters = DynamicsParameters(
        left_turn_gain=float(fit["left_turn_gain"]),
        right_turn_gain=float(fit["right_turn_gain"]),
        velocity_feedback=float(fit["velocity_feedback"]),
    )
    traces = {}
    for phase in TURN_PHASES:
        segment = segment_rows(rows, phase)
        observed = integrated_trace(segment, axis, bias[axis_index])
        turn_input = phase_input(rows_for(rows, phase))[1]
        predicted = simulated_trace(segment, phase, turn_input, parameters)
        stride = max(1, len(segment) // 180)
        traces[phase] = [
            {
                "time_s": round(float(segment[index]["time_s"]) - float(segment[0]["time_s"]), 4),
                "physical_degrees": round(observed[index], 3),
                "simulated_degrees": round(predicted[index], 3),
            }
            for index in range(0, len(segment), stride)
        ]
    return traces


class Lab:
    def __init__(self, pi_url: str, jetson_url: str = "http://192.168.55.1:8771") -> None:
        self.pi_url = pi_url.rstrip("/")
        self.jetson_url = jetson_url.rstrip("/")
        self.model = TinyMLP.load(HIGH_FIDELITY_POLICY_PATH)
        self.scenarios = generate_scenarios(40, 101)

    def run_scenario(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("request must be an object")
        scenario_id = int(payload.get("scenario_id", 0))
        if not 0 <= scenario_id < len(self.scenarios):
            raise ValueError("scenario_id is outside the available range")
        policy_name = payload.get("policy", "learned")
        if policy_name == "learned":
            policy = LearnedNavigationPolicy(self.model)
        elif policy_name == "expert":
            policy = ExpertPolicy()
        else:
            raise ValueError("policy must be learned or expert")
        dynamics = DynamicsParameters(
            floor_friction=float(payload.get("floor_friction", 1.0)),
            left_turn_gain=float(payload.get("left_turn_gain", 0.90)),
            right_turn_gain=float(payload.get("right_turn_gain", 0.84)),
            velocity_feedback=float(payload.get("velocity_feedback", 0.004)),
        )
        trace: list[dict[str, object]] = []
        result = run_navigation_scenario(
            self.scenarios[scenario_id],
            policy,
            dynamics=dynamics,
            forced_stuck_window=(1.5, 2.5) if payload.get("inject_stuck") else None,
            trace=trace,
        )
        scenario = self.scenarios[scenario_id]
        return {
            "kind": "waypoint_navigation",
            "scenario": {
                "scenario_id": scenario.scenario_id,
                "waypoints": scenario.waypoints,
                "obstacles": [asdict(obstacle) for obstacle in scenario.obstacles],
            },
            "dynamics": asdict(dynamics),
            "result": result.to_dict(),
            "trace": trace,
            "provenance": SIM_PROVENANCE,
        }

    def run_target_scenario(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("request must be an object")
        bearing_degrees = float(payload.get("bearing_degrees", 170.0))
        distance_m = float(payload.get("distance_m", 1.5))
        if not -180.0 <= bearing_degrees <= 180.0:
            raise ValueError("bearing_degrees must be between -180 and 180")
        if not 0.3 <= distance_m <= 3.0:
            raise ValueError("distance_m must be between 0.3 and 3.0")
        bearing = math.radians(bearing_degrees)
        target = VisualTarget(
            x_m=distance_m * math.cos(bearing),
            y_m=distance_m * math.sin(bearing),
        )
        dynamics = DynamicsParameters(
            floor_friction=float(payload.get("floor_friction", 1.0)),
            left_turn_gain=float(payload.get("left_turn_gain", 0.90)),
            right_turn_gain=float(payload.get("right_turn_gain", 0.84)),
            velocity_feedback=float(payload.get("velocity_feedback", 0.004)),
        )
        trace: list[dict[str, object]] = []
        result = run_target_scenario(
            target,
            dynamics=dynamics,
            duration_s=25.0,
            trace=trace,
        )
        return {
            "kind": "target_search",
            "scenario": {
                "target": asdict(target),
                "bearing_degrees": bearing_degrees,
                "distance_m": distance_m,
                "camera_horizontal_fov_degrees": math.degrees(
                    target.horizontal_fov_rad
                ),
            },
            "dynamics": asdict(dynamics),
            "result": result.to_dict(),
            "trace": trace,
            "provenance": {
                **SIM_PROVENANCE,
                "controller": "shared target geometry controller with simplified camera model",
            },
        }

    def run_policy_arena(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("request must be an object")
        scenario_seed = int(payload.get("scenario_seed", 9201))
        scenario_id = int(payload.get("scenario_id", 0))
        if not 0 <= scenario_id < 40:
            raise ValueError("scenario_id must be between 0 and 39")
        scenario = generate_high_fidelity_scenarios(40, scenario_seed)[scenario_id]
        policy_name = str(payload.get("policy", "learned"))
        if policy_name == "learned":
            policy = LearnedNavigationPolicy(self.model)
        elif policy_name == "expert":
            policy = ExpertPolicy()
        else:
            raise ValueError("policy must be learned or expert")
        dynamics = randomized_dynamics(scenario_seed * 100 + scenario_id)
        fidelity = randomized_fidelity(scenario_seed * 100 + scenario_id + 50_000)
        episode = run_policy_episode(
            scenario,
            policy,
            dynamics=dynamics,
            fidelity=fidelity,
            seed=scenario_seed + scenario_id,
            forced_stuck_window=(1.5, 2.5) if payload.get("inject_stuck") else None,
            capture_frames=bool(payload.get("capture_frames", True)),
            frame_period_s=0.25,
        )
        return {
            "kind": "high_fidelity_policy_arena",
            **episode,
            "evaluation_reference": read_json(HIGH_FIDELITY_EVALUATION_PATH)["summary"],
        }

    def run_exploration_scenario(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("request must be an object")
        target_x_m = float(payload.get("target_x_m", 1.35))
        target_y_m = float(payload.get("target_y_m", 0.90))
        if not -1.7 <= target_x_m <= 1.7 or not -1.2 <= target_y_m <= 1.2:
            raise ValueError("target must remain inside the simulated room")
        world = ExplorationWorld(target=VisualTarget(target_x_m, target_y_m))
        dynamics = DynamicsParameters(
            floor_friction=float(payload.get("floor_friction", 1.0)),
            left_turn_gain=float(payload.get("left_turn_gain", 0.90)),
            right_turn_gain=float(payload.get("right_turn_gain", 0.84)),
            velocity_feedback=float(payload.get("velocity_feedback", 0.004)),
            left_drive_scale=float(payload.get("left_drive_scale", 1.0)),
            right_drive_scale=float(payload.get("right_drive_scale", 1.0)),
        )
        fidelity = FidelityParameters(
            seed=int(payload.get("seed", 17)),
            range_noise_sigma_m=float(payload.get("range_noise_sigma_m", 0.012)),
            range_dropout_probability=float(payload.get("range_dropout_probability", 0.01)),
            range_latency_ms=int(payload.get("range_latency_ms", 40)),
            camera_period_ms=int(payload.get("camera_period_ms", 100)),
            camera_latency_ms=int(payload.get("camera_latency_ms", 80)),
            camera_dropout_probability=float(payload.get("camera_dropout_probability", 0.02)),
            command_latency_ms=int(payload.get("command_latency_ms", 40)),
            odometry_noise_sigma_mps=float(payload.get("odometry_noise_sigma_mps", 0.008)),
            gyro_noise_sigma_dps=float(payload.get("gyro_noise_sigma_dps", 0.12)),
            rendered_camera=bool(payload.get("rendered_camera", True)),
        )
        trace: list[dict[str, object]] = []
        camera_frames: list[dict[str, object]] = []
        result = run_exploration(
            world=world,
            dynamics=dynamics,
            fidelity=fidelity,
            odometry_scale=float(payload.get("odometry_scale", 0.97)),
            gyro_scale=float(payload.get("gyro_scale", 1.015)),
            gyro_bias_dps=float(payload.get("gyro_bias_dps", 0.10)),
            trace=trace,
            camera_frames=camera_frames,
        )
        return {
            "kind": "mapping_exploration",
            "result": {key: value for key, value in result.items() if key not in {"map", "world", "frontiers", "camera_frames"}},
            "map": result["map"],
            "world": result["world"],
            "frontiers": result["frontiers"],
            "trace": trace,
            "camera_frames": camera_frames,
            "provenance": {
                **SIM_PROVENANCE,
                "localization": "dead reckoning with explicit scale and gyro error",
                "mapping": "log-odds occupancy grid from delayed/noisy MuJoCo geometry rays",
                "planning": "frontier selection plus A* on known-free cells",
                "camera": "MuJoCo RGB render processed by an HSV pixel detector",
                "contacts": "MuJoCo solver response; no analytic snap-back",
                "observation_gap": "physical rover lacks the simulated metric range scan",
            },
        }

    def predict(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("request must be an object")
        values = numpy.asarray([float(payload[name]) for name in INPUT_NAMES])
        hidden, output = self.model.forward(values)
        return {
            "inputs": dict(zip(INPUT_NAMES, values.tolist())),
            "hidden": hidden.tolist(),
            "outputs": {"forward": float(output[0]), "turn": float(output[1])},
        }

    @staticmethod
    def _request_json(
        base_url: str, path: str, payload: object | None = None
    ) -> dict[str, object]:
        request = Request(
            f"{base_url}{path}",
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="GET" if payload is None else "POST",
        )
        with urlopen(request, timeout=2.0) as response:
            return json.loads(response.read())

    def camera_frame(self) -> tuple[bytes, dict[str, str]]:
        with urlopen(f"{self.pi_url}/api/camera/frame.jpg", timeout=2.0) as response:
            frame = response.read()
            headers = {}
            for name in ("X-Frame-Id", "X-Frame-Age-Ms"):
                value = response.headers.get(name)
                if value is None or not value.isascii() or not value.isdecimal():
                    raise ValueError(f"camera metadata missing or invalid: {name}")
                headers[name] = value
            return frame, headers

    def manual_command(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("manual command must be an object")
        return self._request_json(self.pi_url, "/api/command", payload)

    def heading_hold(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict) or not isinstance(payload.get("enabled"), bool):
            raise ValueError("heading hold requires a boolean enabled value")
        return self._request_json(self.pi_url, "/api/heading-hold", payload)

    def autonomy_command(self, command: str) -> dict[str, object]:
        paths = {
            "probe": "/api/probe",
            "arm": "/api/arm",
            "disarm": "/api/disarm",
            "monitor-start": "/api/monitor/start",
            "monitor-stop": "/api/monitor/stop",
        }
        if command not in paths:
            raise ValueError("unsupported autonomy command")
        return self._request_json(self.jetson_url, paths[command], {})

    def live(self) -> dict[str, object]:
        endpoints = {
            "status": (self.pi_url, "/api/status"),
            "telemetry": (self.pi_url, "/api/telemetry"),
            "heading": (self.pi_url, "/api/heading"),
            "jetson": (self.jetson_url, "/api/status"),
        }

        def fetch(base_url: str, path: str) -> dict[str, object]:
            try:
                return self._request_json(base_url, path)
            except (OSError, URLError, json.JSONDecodeError) as error:
                return {"error": str(error)}

        with ThreadPoolExecutor(max_workers=len(endpoints)) as executor:
            futures = {
                name: executor.submit(fetch, base_url, path)
                for name, (base_url, path) in endpoints.items()
            }
            return {name: future.result() for name, future in futures.items()}


def make_handler(lab: Lab):
    class LabHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            try:
                path = self.path.split("?", 1)[0]
                if path == "/":
                    self._send(HTTPStatus.OK, UI_PATH.read_bytes(), "text/html; charset=utf-8")
                elif path == "/camera_freshness.js":
                    self._send(HTTPStatus.OK, UI_PATH.with_name("camera_freshness.js").read_bytes(), "text/javascript")
                elif path == "/manual_drive.js":
                    self._send(HTTPStatus.OK, UI_PATH.with_name("manual_drive.js").read_bytes(), "text/javascript")
                elif path == "/api/summary":
                    self._json(HTTPStatus.OK, build_summary())
                elif path == "/api/turn-traces":
                    self._json(HTTPStatus.OK, build_turn_traces())
                elif path == "/api/live":
                    self._json(HTTPStatus.OK, lab.live())
                elif path == "/api/camera/frame.jpg":
                    frame, headers = lab.camera_frame()
                    self._send(HTTPStatus.OK, frame, "image/jpeg", headers)
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})

        def do_POST(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                path = self.path.split("?", 1)[0]
                if path == "/api/run":
                    self._json(HTTPStatus.OK, lab.run_scenario(payload))
                elif path == "/api/run-target":
                    self._json(HTTPStatus.OK, lab.run_target_scenario(payload))
                elif path == "/api/run-policy-arena":
                    self._json(HTTPStatus.OK, lab.run_policy_arena(payload))
                elif path == "/api/run-exploration":
                    self._json(HTTPStatus.OK, lab.run_exploration_scenario(payload))
                elif path == "/api/predict":
                    self._json(HTTPStatus.OK, lab.predict(payload))
                elif path == "/api/manual":
                    self._json(HTTPStatus.OK, lab.manual_command(payload))
                elif path == "/api/heading-hold":
                    self._json(HTTPStatus.OK, lab.heading_hold(payload))
                elif path.startswith("/api/autonomy/"):
                    self._json(
                        HTTPStatus.OK,
                        lab.autonomy_command(path.rsplit("/", 1)[-1]),
                    )
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except (OSError, URLError, ValueError, KeyError, json.JSONDecodeError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

        def _json(self, status: HTTPStatus, payload: object) -> None:
            self._send(status, json.dumps(payload, separators=(",", ":")).encode(), "application/json")

        def _send(self, status: HTTPStatus, body: bytes, content_type: str,
                  headers: dict[str, str] | None = None) -> None:
            try:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                return

        def log_message(self, _format: str, *_args: object) -> None:
            return None

    return LabHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument("--pi-url", default="http://192.168.0.87:8765")
    parser.add_argument("--jetson-url", default="http://192.168.55.1:8771")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    server = ThreadingHTTPServer(
        (args.host, args.port), make_handler(Lab(args.pi_url, args.jetson_url))
    )
    print(f"Autonomy Lab listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
