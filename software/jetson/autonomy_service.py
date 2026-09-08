#!/usr/bin/env python3
"""Serve a fail-closed TensorRT target-autonomy process on the Jetson."""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import signal
import threading
import time
from typing import Callable, Protocol
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from autonomy_controller import Action, ControlState, Observation, TargetController
from mission_runtime import (
    ExecutionKind,
    RuntimeConfig,
    SearchProgress,
    plan_execution,
)
from tensorrt_yolo import COCO_NAMES
from visual_odometry import VisualMotionEstimator


DEFAULT_PI_URLS = (
    "http://192.168.55.100:8765",
    "http://127.0.0.1:8765",
)
DEFAULT_UI = Path(__file__).with_name("autonomy.html")


class DetectionLike(Protocol):
    horizontal_error: float
    area_ratio: float
    bottom_edge_ratio: float

    def to_dict(self) -> dict[str, object]: ...


class Detector(Protocol):
    def detect(
        self, jpeg: bytes
    ) -> tuple[DetectionLike | None, dict[str, float]]: ...


class Gateway(Protocol):
    @property
    def active_url(self) -> str | None: ...

    def fetch_frame(
        self, after: int, timeout: float
    ) -> tuple[bytes, int, int] | None: ...

    def send_action(self, forward: float, turn: float, timeout: float) -> float: ...

    def start_heading_turn(self, target_degrees: float, timeout: float) -> None: ...

    def heading_status(self, timeout: float) -> dict[str, object]: ...


class FailoverPiGateway:
    """Try local USB networking first, then the development SSH tunnel."""

    def __init__(self, base_urls: tuple[str, ...]) -> None:
        if not base_urls:
            raise ValueError("at least one Pi URL is required")
        self.base_urls = tuple(url.rstrip("/") for url in base_urls)
        self._active_url: str | None = None
        self.lock = threading.Lock()

    @property
    def active_url(self) -> str | None:
        with self.lock:
            return self._active_url

    def _ordered_urls(self) -> tuple[str, ...]:
        active = self.active_url
        if active is None:
            return self.base_urls
        return (active,) + tuple(url for url in self.base_urls if url != active)

    def _mark_active(self, url: str) -> None:
        with self.lock:
            self._active_url = url

    def fetch_frame(
        self, after: int, timeout: float
    ) -> tuple[bytes, int, int] | None:
        errors = []
        query = urlencode({"after": after})
        for base_url in self._ordered_urls():
            try:
                with urlopen(
                    f"{base_url}/api/camera/frame.jpg?{query}", timeout=timeout
                ) as response:
                    self._mark_active(base_url)
                    if response.status == HTTPStatus.NO_CONTENT:
                        return None
                    return (
                        response.read(),
                        int(response.headers.get("X-Frame-Id", after + 1)),
                        int(response.headers.get("X-Frame-Age-Ms", 0)),
                    )
            except (OSError, URLError) as error:
                errors.append(f"{base_url}: {error}")
        raise OSError("Pi camera unavailable; " + "; ".join(errors))

    def send_action(self, forward: float, turn: float, timeout: float) -> float:
        body = json.dumps({"forward": forward, "turn": turn}).encode()
        errors = []
        for base_url in self._ordered_urls():
            request = Request(
                f"{base_url}/api/action",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            started = time.monotonic()
            try:
                with urlopen(request, timeout=timeout) as response:
                    if response.status != HTTPStatus.OK:
                        raise OSError(f"HTTP {response.status}")
                    response.read()
                self._mark_active(base_url)
                return round((time.monotonic() - started) * 1000.0, 2)
            except (OSError, URLError) as error:
                errors.append(f"{base_url}: {error}")
        raise OSError("Pi action API unavailable; " + "; ".join(errors))

    def _heading_request(
        self, path: str, timeout: float, body: dict[str, float] | None = None
    ) -> dict[str, object]:
        errors = []
        for base_url in self._ordered_urls():
            request = Request(
                f"{base_url}{path}",
                data=None if body is None else json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
                method="GET" if body is None else "POST",
            )
            try:
                with urlopen(request, timeout=timeout) as response:
                    result = json.loads(response.read())
                self._mark_active(base_url)
                return result
            except (OSError, URLError) as error:
                errors.append(f"{base_url}: {error}")
        raise OSError("Pi heading API unavailable; " + "; ".join(errors))

    def start_heading_turn(self, target_degrees: float, timeout: float) -> None:
        self._heading_request(
            "/api/heading/turn", timeout, {"target_degrees": target_degrees}
        )

    def heading_status(self, timeout: float) -> dict[str, object]:
        return self._heading_request("/api/heading", timeout)


class AutonomyService:
    """Own detector lifecycle, arming state, control loop, and safe stop."""

    def __init__(
        self,
        gateway: Gateway,
        detector_factory: Callable[[str, float], Detector],
        *,
        config: RuntimeConfig | None = None,
        timeout: float = 1.0,
        mission_timeout_s: float = 45.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.gateway = gateway
        self.detector_factory = detector_factory
        self.config = config or RuntimeConfig()
        self.timeout = timeout
        if not math.isfinite(mission_timeout_s) or not 1 <= mission_timeout_s <= 120:
            raise ValueError("mission timeout must be between 1 and 120 seconds")
        self.mission_timeout_s = mission_timeout_s
        self.mission_deadline: float | None = None
        self.clock = clock
        self.lock = threading.Lock()
        self.command_lock = threading.Lock()
        self.wake = threading.Event()
        self.probe_requested = threading.Event()
        self.shutdown = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.detector: Detector | None = None
        self.detector_key: tuple[str, float] | None = None
        self.controller = TargetController(self.config.controller_config())
        self.armed = False
        self.monitoring = False
        self.state = "starting"
        self.reason = "initializing TensorRT engine"
        self.frame_id = -1
        self.frames_processed = 0
        self.mission_frames = 0
        self.mission_state_counts: dict[str, int] = {}
        self.last_target_seen_at: float | None = None
        self.last_seen_horizontal_error = 0.0
        self.last_seen_area_ratio = 0.0
        self.last_seen_bottom_edge_ratio = 0.0
        self.closest_area_ratio = 0.0
        self.closest_bottom_edge_ratio = 0.0
        self.search_steps = 0
        self.search_cycles = 0
        self.last_detection: dict[str, object] | None = None
        self.last_observation: dict[str, object] | None = None
        self.last_action: dict[str, object] = {
            "forward": 0.0,
            "turn": 0.0,
            "state": "disarmed",
        }
        self.perception_timing: dict[str, float] | None = None
        self.command_ms: float | None = None
        self.pulse_stop_ms: float | None = None
        self.search_pulse_done = threading.Event()
        self.search_pulse_done.set()
        self.last_observation_frames = 0
        self.fault: str | None = None
        self.visual_motion = VisualMotionEstimator()
        self.motion_status: dict[str, object] = self.visual_motion.status()
        self.mission_trace: deque[dict[str, object]] = deque(maxlen=240)
        self.updated_at = self._timestamp()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.disarm("service shutdown")
        self.shutdown.set()
        self.wake.set()
        self.thread.join(timeout=3.0)

    def status(self) -> dict[str, object]:
        with self.lock:
            return {
                "state": self.state,
                "armed": self.armed,
                "monitoring": self.monitoring,
                "mission_timeout_s": self.mission_timeout_s,
                "mission_remaining_s": (
                    round(max(0.0, self.mission_deadline - self.clock()), 2)
                    if self.armed and self.mission_deadline is not None else None
                ),
                "reason": self.reason,
                "fault": self.fault,
                "target": self.config.target,
                "confidence": self.config.confidence,
                "controller_config": asdict(self.config),
                "detector_ready": self.detector_key
                == (self.config.target, self.config.confidence),
                "pi_url": self.gateway.active_url,
                "frame_id": self.frame_id,
                "frames_processed": self.frames_processed,
                "mission_frames": self.mission_frames,
                "mission_state_counts": self.mission_state_counts.copy(),
                "search_steps": self.search_steps,
                "search_cycles": self.search_cycles,
                "closest_area_ratio": self.closest_area_ratio,
                "closest_bottom_edge_ratio": self.closest_bottom_edge_ratio,
                "last_seen_horizontal_error": self.last_seen_horizontal_error,
                "last_seen_area_ratio": self.last_seen_area_ratio,
                "last_seen_bottom_edge_ratio": self.last_seen_bottom_edge_ratio,
                "detection": self.last_detection,
                "observation": self.last_observation,
                "action": self.last_action,
                "perception_timing": self.perception_timing,
                "command_ms": self.command_ms,
                "pulse_stop_ms": self.pulse_stop_ms,
                "observation_frames": self.last_observation_frames,
                "updated_at": self.updated_at,
                "perception_source": self._perception_source_locked(),
                "visual_motion": self.motion_status,
                "mission_trace": list(self.mission_trace),
            }

    def _perception_source_locked(self) -> dict[str, object]:
        if self.armed:
            return {"kind": "live_control", "live": True, "label": "LIVE CONTROL"}
        if self.monitoring:
            return {"kind": "live_monitor", "live": True, "label": "LIVE MONITOR"}
        if self.state == "probe_complete":
            return {"kind": "captured_probe", "live": False, "label": "LAST PROBE"}
        if self.frames_processed:
            return {"kind": "stored_result", "live": False, "label": "STORED RESULT"}
        return {"kind": "none", "live": False, "label": "NO INFERENCE"}

    def configure(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("configuration must be an object")
        with self.lock:
            if self.armed or self.monitoring:
                raise RuntimeError("disarm and stop monitoring before changing configuration")
            values = asdict(self.config)
            for name in values:
                if name in payload:
                    values[name] = payload[name]
            typed = {
                name: (str if name == "target" else int if name in {
                    "max_frame_age_ms", "turn_pulse_ms", "alignment_pulse_ms",
                    "reacquire_hold_ms", "approach_pulse_ms", "maximum_search_steps",
                    "recovery_reverse_ms", "maximum_search_cycles", "observation_frames",
                    "observation_interval_ms",
                } else float)(value)
                for name, value in values.items()
            }
            config = RuntimeConfig(**typed)
            self._validate_config(config)
            detector_changed = (config.target, config.confidence) != (
                self.config.target,
                self.config.confidence,
            )
            self.config = config
            self.controller = TargetController(config.controller_config())
            self.fault = None
            if detector_changed:
                self.state = "loading"
                self.reason = "loading detector configuration"
            else:
                self.state = "disarmed"
                self.reason = "configured; explicit arm required"
            self.updated_at = self._timestamp()
        self.wake.set()
        return self.status()

    @staticmethod
    def _validate_config(config: RuntimeConfig) -> None:
        if config.target not in COCO_NAMES:
            raise ValueError(f"target must be one of the COCO classes: {config.target!r}")
        for name in (
            "confidence",
            "target_area_ratio",
            "area_tolerance",
            "arrival_bottom_ratio",
            "arrival_min_area_ratio",
            "close_loss_area_ratio",
            "minimum_target_area_ratio",
            "alignment_tolerance",
            "turn_gain",
            "max_forward",
            "max_turn",
            "search_turn",
            "min_turn",
            "recovery_reverse",
        ):
            value = getattr(config, name)
            if not 0.0 < value <= 1.0:
                raise ValueError(f"{name} must be greater than 0 and at most 1")
        if config.min_turn > config.max_turn:
            raise ValueError("min_turn must not exceed max_turn")
        if config.close_loss_area_ratio > config.target_area_ratio:
            raise ValueError("close_loss_area_ratio must not exceed target_area_ratio")
        if config.minimum_target_area_ratio >= config.close_loss_area_ratio:
            raise ValueError(
                "minimum_target_area_ratio must be below close_loss_area_ratio"
            )
        if config.arrival_min_area_ratio >= config.target_area_ratio:
            raise ValueError("arrival_min_area_ratio must be below target_area_ratio")
        if config.max_frame_age_ms <= 0:
            raise ValueError("max_frame_age_ms must be positive")
        if not 0 <= config.turn_pulse_ms <= 300:
            raise ValueError("turn_pulse_ms must be between 0 and 300")
        if not 0 <= config.alignment_pulse_ms <= 300:
            raise ValueError("alignment_pulse_ms must be between 0 and 300")
        if not 0 <= config.reacquire_hold_ms <= 2000:
            raise ValueError("reacquire_hold_ms must be between 0 and 2000")
        if not 5.0 <= config.search_step_degrees <= 90.0:
            raise ValueError("search_step_degrees must be between 5 and 90")
        if not 10.0 <= config.camera_half_fov_degrees <= 90.0:
            raise ValueError("camera_half_fov_degrees must be between 10 and 90")
        if not 50 <= config.approach_pulse_ms <= 350:
            raise ValueError("approach_pulse_ms must be between 50 and 350")
        if not 4 <= config.maximum_search_steps <= 72:
            raise ValueError("maximum_search_steps must be between 4 and 72")
        if not 50 <= config.recovery_reverse_ms <= 350:
            raise ValueError("recovery_reverse_ms must be between 50 and 350")
        if not 1 <= config.maximum_search_cycles <= 5:
            raise ValueError("maximum_search_cycles must be between 1 and 5")
        if not 1 <= config.observation_frames <= 5:
            raise ValueError("observation_frames must be between 1 and 5")
        if not 0 <= config.observation_interval_ms <= 500:
            raise ValueError("observation_interval_ms must be between 0 and 500")

    def arm(self) -> dict[str, object]:
        with self.lock:
            expected = (self.config.target, self.config.confidence)
            if self.detector_key != expected:
                raise RuntimeError("detector is not ready")
            self.controller = TargetController(self.config.controller_config())
            self.armed = True
            self.mission_deadline = self.clock() + self.mission_timeout_s
            self.monitoring = False
            self.state = "armed"
            self.reason = "closed-loop target autonomy active"
            self.fault = None
            self.frame_id = -1
            self.mission_frames = 0
            self.mission_state_counts = {}
            self.last_target_seen_at = None
            self.last_seen_horizontal_error = 0.0
            self.last_seen_area_ratio = 0.0
            self.last_seen_bottom_edge_ratio = 0.0
            self.closest_area_ratio = 0.0
            self.closest_bottom_edge_ratio = 0.0
            self.search_steps = 0
            self.search_cycles = 0
            self.mission_trace.clear()
            self.updated_at = self._timestamp()
        self.wake.set()
        return self.status()

    def disarm(self, reason: str = "operator disarm") -> dict[str, object]:
        # Serialize with _step so this stop is ordered after any in-flight action.
        with self.command_lock:
            with self.lock:
                self.armed = False
                self.monitoring = False
                self.state = "disarmed"
                self.reason = reason
                self.last_action = {
                    "forward": 0.0,
                    "turn": 0.0,
                    "state": "disarmed",
                }
                self.updated_at = self._timestamp()
            self._safe_stop()
        self.wake.set()
        return self.status()

    def start_monitor(self) -> dict[str, object]:
        with self.lock:
            if self.armed:
                raise RuntimeError("disarm before starting perception monitor")
            if self.detector_key != (self.config.target, self.config.confidence):
                raise RuntimeError("detector is not ready")
            self.controller = TargetController(self.config.controller_config())
            self.monitoring = True
            self.state = "monitoring"
            self.reason = "live perception active; motor commands disabled"
            self.fault = None
            self.updated_at = self._timestamp()
        self.wake.set()
        return self.status()

    def stop_monitor(self) -> dict[str, object]:
        with self.lock:
            self.monitoring = False
            if not self.armed:
                self.state = "disarmed"
                self.reason = "perception monitor stopped; explicit arm required"
                self.updated_at = self._timestamp()
        self.wake.set()
        return self.status()

    def probe(self, timeout: float = 8.0) -> dict[str, object]:
        with self.lock:
            if self.armed:
                raise RuntimeError("disarm before running a perception probe")
            if self.monitoring:
                raise RuntimeError("stop monitoring before running a perception probe")
            if self.detector_key != (self.config.target, self.config.confidence):
                raise RuntimeError("detector is not ready")
            self.controller = TargetController(self.config.controller_config())
            self.last_target_seen_at = None
            self.last_seen_horizontal_error = 0.0
            self.last_seen_area_ratio = 0.0
            self.last_seen_bottom_edge_ratio = 0.0
            self.closest_area_ratio = 0.0
            self.closest_bottom_edge_ratio = 0.0
            self.state = "probing"
            self.reason = "fetching one frame without sending a motor command"
            self.fault = None
            self.updated_at = self._timestamp()
        self.probe_requested.set()
        self.wake.set()
        if not self.probe_requested.wait(timeout):
            raise RuntimeError("perception probe did not start")
        deadline = self.clock() + timeout
        while self.probe_requested.is_set() and self.clock() < deadline:
            time.sleep(0.02)
        if self.probe_requested.is_set():
            raise RuntimeError("perception probe timed out")
        return self.status()

    def _safe_stop(self) -> None:
        try:
            self.gateway.send_action(0.0, 0.0, self.timeout)
        except OSError:
            # If transport is gone, the Pi's independent 350 ms watchdog stops it.
            pass

    def _load_detector_if_needed(self) -> None:
        with self.lock:
            key = (self.config.target, self.config.confidence)
            if self.detector_key == key:
                return
            self.state = "loading"
            self.reason = f"loading TensorRT detector for {key[0]}"
            self.updated_at = self._timestamp()
        detector = self.detector_factory(*key)
        with self.lock:
            self.detector = detector
            self.detector_key = key
            self.state = "disarmed"
            self.reason = "detector ready; explicit arm required"
            self.fault = None
            self.updated_at = self._timestamp()

    def _record_fault(self, error: Exception) -> None:
        with self.lock:
            self.armed = False
            self.monitoring = False
            self.state = "fault"
            self.reason = "autonomy disarmed by fault"
            self.fault = str(error)
            self.last_action = {
                "forward": 0.0,
                "turn": 0.0,
                "state": "fault_stop",
            }
            self.updated_at = self._timestamp()
        self._safe_stop()

    def _controller_action(
        self, detection: DetectionLike | None, observation: Observation
    ) -> Action:
        now = self.clock()
        if detection is not None:
            self.last_target_seen_at = now
            self.last_seen_horizontal_error = observation.horizontal_error
            self.last_seen_area_ratio = observation.area_ratio
            self.last_seen_bottom_edge_ratio = observation.bottom_edge_ratio
            self.closest_area_ratio = max(
                self.closest_area_ratio, observation.area_ratio
            )
            self.closest_bottom_edge_ratio = max(
                self.closest_bottom_edge_ratio, observation.bottom_edge_ratio
            )
        elif (
            self.last_target_seen_at is not None
            and (now - self.last_target_seen_at) * 1000.0
            < self.config.reacquire_hold_ms
            and abs(self.last_seen_horizontal_error)
            <= self.config.alignment_tolerance
            and (
                self.last_seen_area_ratio >= self.config.close_loss_area_ratio
                or (
                    self.last_seen_bottom_edge_ratio
                    >= self.config.arrival_bottom_ratio
                    and self.last_seen_area_ratio
                    >= self.config.arrival_min_area_ratio
                )
            )
            and self.last_action.get("state")
            in {
                ControlState.APPROACHING.value,
                ControlState.REACQUIRING.value,
            }
        ):
            self.controller.arrived = True
            return Action(0.0, 0.0, ControlState.ARRIVED)

        action = self.controller.update(observation)
        if (
            detection is None
            and action.state == ControlState.SEARCHING
            and self.last_target_seen_at is not None
            and (now - self.last_target_seen_at) * 1000.0
            < self.config.reacquire_hold_ms
        ):
            return Action(0.0, 0.0, ControlState.REACQUIRING)
        return action

    def _motion_allowed_locked(self) -> bool:
        # Caller holds self.lock; check again after slow inference/network work.
        if not self.armed:
            return False
        if self.mission_deadline is None or self.clock() >= self.mission_deadline:
            raise TimeoutError(f"mission exceeded {self.mission_timeout_s:g} second limit")
        return True

    def _run_heading_turn(self, target_degrees: float) -> float:
        started = self.clock()
        with self.command_lock:
            with self.lock:
                if not self._motion_allowed_locked():
                    return 0.0
            self.gateway.start_heading_turn(target_degrees, self.timeout)

        deadline = self.clock() + 10.0
        while self.clock() < deadline:
            with self.lock:
                armed = self._motion_allowed_locked()
            if not armed:
                return round((self.clock() - started) * 1000.0, 2)
            status = self.gateway.heading_status(self.timeout)
            if not status.get("active"):
                if status.get("state") != "complete":
                    raise RuntimeError(
                        f"heading turn ended in {status.get('state')}: "
                        f"{status.get('message')}"
                    )
                return round((self.clock() - started) * 1000.0, 2)
            time.sleep(0.05)
        self._safe_stop()
        raise TimeoutError("heading turn exceeded 10 second timeout")

    def _run_motor_pulse(
        self, forward: float, turn: float, duration_ms: int
    ) -> tuple[float, float]:
        if not self.search_pulse_done.wait(1.0):
            raise TimeoutError("previous search pulse did not stop")
        with self.command_lock:
            with self.lock:
                if not self._motion_allowed_locked():
                    return 0.0, 0.0
            command_ms = self.gateway.send_action(forward, turn, self.timeout)
            time.sleep(duration_ms / 1000.0)
            stop_ms = self.gateway.send_action(0.0, 0.0, self.timeout)
        return command_ms, stop_ms

    def _start_observed_search_pulse(self, turn: float) -> float:
        if not self.search_pulse_done.wait(1.0):
            raise TimeoutError("previous search pulse did not stop")
        with self.command_lock:
            with self.lock:
                if not self._motion_allowed_locked():
                    return 0.0
            command_ms = self.gateway.send_action(0.0, turn, self.timeout)
            self.search_pulse_done.clear()

        def stop_after_pulse() -> None:
            try:
                time.sleep(self.config.turn_pulse_ms / 1000.0)
                with self.command_lock:
                    stop_ms = self.gateway.send_action(0.0, 0.0, self.timeout)
                with self.lock:
                    self.pulse_stop_ms = stop_ms
            finally:
                self.search_pulse_done.set()

        threading.Thread(target=stop_after_pulse, daemon=True).start()
        return command_ms

    def _observe(
        self,
    ) -> tuple[DetectionLike | None, Observation, dict[str, float], int, int, bytes] | None:
        detector = self.detector
        if detector is None:
            raise RuntimeError("detector unavailable")
        frame_id = self.frame_id
        latest = None
        samples = 0
        for index in range(self.config.observation_frames):
            fetched = self.gateway.fetch_frame(frame_id, self.timeout)
            if fetched is not None:
                jpeg, frame_id, source_age_ms = fetched
                detection, timing = detector.detect(jpeg)
                if (
                    detection is not None
                    and detection.area_ratio < self.config.minimum_target_area_ratio
                ):
                    detection = None
                samples += 1
                observation = Observation(
                    target_visible=detection is not None,
                    horizontal_error=detection.horizontal_error if detection else 0.0,
                    area_ratio=detection.area_ratio if detection else 0.0,
                    frame_age_ms=round(source_age_ms + timing["total_ms"]),
                    bottom_edge_ratio=(
                        getattr(detection, "bottom_edge_ratio", 0.0)
                        if detection
                        else 0.0
                    ),
                )
                latest = detection, observation, timing, frame_id, samples, jpeg
                if detection is not None and observation.frame_age_ms <= self.config.max_frame_age_ms:
                    break
            if index + 1 < self.config.observation_frames:
                time.sleep(self.config.observation_interval_ms / 1000.0)
        return latest

    def _step(self, *, send_action: bool = True, monitoring: bool = False) -> None:
        with self.lock:
            if send_action and not self._motion_allowed_locked():
                return
        measured = self._observe()
        if measured is None:
            return
        detection, observation, timing, frame_id, observation_frames, jpeg = measured
        motion_status = self.visual_motion.process(jpeg)
        action = self._controller_action(detection, observation)
        command = plan_execution(
            action,
            observation,
            self.config,
            SearchProgress(self.search_steps, self.search_cycles),
        )
        action = command.action
        command_ms = None
        pulse_stop_ms = None
        if send_action:
            if command.kind == ExecutionKind.FAULT:
                raise RuntimeError(command.error or "mission execution fault")
            if command.kind == ExecutionKind.HEADING_TURN:
                command_ms = self._run_heading_turn(command.heading_degrees)
            elif command.kind == ExecutionKind.MOTOR_PULSE:
                command_ms, pulse_stop_ms = self._run_motor_pulse(
                    action.forward, action.turn, command.duration_ms
                )
            else:
                with self.command_lock:
                    with self.lock:
                        if not self._motion_allowed_locked():
                            return
                    command_ms = self.gateway.send_action(0.0, 0.0, self.timeout)
            self.search_steps = command.progress.steps
            self.search_cycles = command.progress.cycles
            if command.flip_search_direction:
                self.controller.search_direction *= -1.0
        with self.lock:
            if send_action and not self.armed:
                return
            if monitoring and not self.monitoring:
                return
            self.frame_id = frame_id
            self.frames_processed += observation_frames
            self.last_observation_frames = observation_frames
            if send_action:
                self.mission_frames += 1
                state_name = action.state.value
                self.mission_state_counts[state_name] = (
                    self.mission_state_counts.get(state_name, 0) + 1
                )
            self.last_detection = detection.to_dict() if detection else None
            self.last_observation = asdict(observation)
            self.last_action = {**action.to_dict(), "sent": send_action}
            self.motion_status = motion_status
            self.perception_timing = timing
            self.command_ms = command_ms
            self.pulse_stop_ms = pulse_stop_ms
            self.state = (
                action.state.value
                if send_action
                else "monitoring" if monitoring else "probe_complete"
            )
            self.reason = (
                "closed-loop command accepted by Pi"
                if send_action
                else (
                    "live perception active; motor commands disabled"
                    if monitoring
                    else "perception measured; no motor command sent"
                )
            )
            self.updated_at = self._timestamp()
            self.mission_trace.append(
                {
                    "timestamp": self.updated_at,
                    "frame_id": frame_id,
                    "observation": asdict(observation),
                    "command": command.to_dict(),
                    "sent": send_action,
                }
            )

    def _run(self) -> None:
        while not self.shutdown.is_set():
            try:
                self._load_detector_if_needed()
                with self.lock:
                    armed = self.armed
                    monitoring = self.monitoring
                if armed:
                    self._step()
                    continue
                if monitoring:
                    self._step(send_action=False, monitoring=True)
                    continue
                if self.probe_requested.is_set():
                    self._step(send_action=False)
                    self.probe_requested.clear()
                    continue
            except Exception as error:
                self._record_fault(error)
                self.probe_requested.clear()
            self.wake.wait(0.20)
            self.wake.clear()


def make_handler(service: AutonomyService, ui_path: Path):
    class Handler(BaseHTTPRequestHandler):
        def do_OPTIONS(self) -> None:
            self._send(HTTPStatus.NO_CONTENT, b"", "text/plain")

        def do_GET(self) -> None:
            if self.path == "/":
                self._send(HTTPStatus.OK, ui_path.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/status":
                self._json(HTTPStatus.OK, service.status())
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:
            try:
                payload = self._read_json()
                if self.path == "/api/arm":
                    self._json(HTTPStatus.OK, service.arm())
                elif self.path == "/api/disarm":
                    self._json(HTTPStatus.OK, service.disarm())
                elif self.path == "/api/monitor/start":
                    self._json(HTTPStatus.OK, service.start_monitor())
                elif self.path == "/api/monitor/stop":
                    self._json(HTTPStatus.OK, service.stop_monitor())
                elif self.path == "/api/probe":
                    self._json(HTTPStatus.OK, service.probe())
                elif self.path == "/api/config":
                    self._json(HTTPStatus.OK, service.configure(payload))
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except ValueError as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            except RuntimeError as error:
                self._json(HTTPStatus.CONFLICT, {"error": str(error)})

        def _read_json(self) -> object:
            length = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(length) or b"{}")

        def _json(self, status: HTTPStatus, value: object) -> None:
            self._send(
                status,
                json.dumps(value, separators=(",", ":")).encode(),
                "application/json",
            )

        def _send(
            self, status: HTTPStatus, body: bytes, content_type: str
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return None

    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8771)
    parser.add_argument("--pi-url", action="append", dest="pi_urls")
    parser.add_argument(
        "--engine", type=Path, default=Path("/home/wooblay/yolov8n-trt10-fp16.engine")
    )
    parser.add_argument("--target", default="orange")
    parser.add_argument("--confidence", type=float, default=0.20)
    parser.add_argument("--ui", type=Path, default=DEFAULT_UI)
    return parser.parse_args()


def stop_on_signal(signum: int, _frame: object) -> None:
    raise KeyboardInterrupt(f"received signal {signum}")


def main() -> int:
    args = parse_args()
    from tensorrt_yolo import TensorRTYoloDetector

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, stop_on_signal)

    service = AutonomyService(
        FailoverPiGateway(tuple(args.pi_urls or DEFAULT_PI_URLS)),
        lambda target, confidence: TensorRTYoloDetector(
            args.engine, target, confidence
        ),
        config=RuntimeConfig(target=args.target, confidence=args.confidence),
    )
    service.start()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(service, args.ui))
    print(f"Jetson autonomy console listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
