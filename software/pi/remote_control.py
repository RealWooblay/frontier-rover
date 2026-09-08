#!/usr/bin/env python3
"""Serve a local browser remote with a motor-command watchdog."""

from __future__ import annotations

import argparse
from collections import deque
import json
import math
import os
import signal
import socket
import statistics
import subprocess
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import parse_qs, urlsplit


MOTIONS = ("forward", "reverse", "left", "right", "stop")
STRAIGHT_LEFT_PWM = 0.40
STRAIGHT_RIGHT_PWM = 0.60
TURN_PWM = 0.50
WATCHDOG_SECONDS = 0.35
POWEROFF_REQUEST_PATH = Path("/run/frontier-rover/poweroff")
DEFAULT_CALIBRATION_PATH = Path("/var/lib/frontier-rover/motor-calibration.json")
DEFAULT_HEADING_HOLD_PATH = Path("/var/lib/frontier-rover/heading-hold.json")
CAMERA_WIDTH = 360
CAMERA_HEIGHT = 640
CAMERA_FRAMERATE = 15
MAX_CAMERA_BUFFER_BYTES = 4 * 1024 * 1024
JPEG_START = b"\xff\xd8"
JPEG_END = b"\xff\xd9"


class Drive(Protocol):
    def set_tank(self, left_speed: float, right_speed: float) -> None: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...


class CameraFrameSource(Protocol):
    def latest(self) -> tuple[bytes, int, int] | None: ...

    def status(self) -> dict[str, object]: ...


class ImuSampleSource(Protocol):
    timestamp_ns: int
    gyro_dps: tuple[float, float, float]


class ImuSensor(Protocol):
    def configure(self) -> None: ...
    def sample(self) -> ImuSampleSource: ...
    def close(self) -> None: ...


class ImuMonitor:
    """Continuously expose bias-corrected yaw rate and relative yaw."""

    def __init__(
        self,
        sensor_factory: Callable[[], ImuSensor],
        *,
        motors_active: Callable[[], bool] = lambda: False,
        clock: Callable[[], float] = time.monotonic,
        sample_hz: float = 50.0,
        bias_sample_count: int = 75,
    ) -> None:
        self.sensor_factory = sensor_factory
        self.motors_active = motors_active
        self.clock = clock
        self.sample_hz = sample_hz
        self.bias_sample_count = bias_sample_count
        self.shutdown = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.lock = threading.Lock()
        self.state = "starting"
        self.error: str | None = None
        self.bias_samples: list[float] = []
        self.bias_dps: float | None = None
        self.noise_dps: float | None = None
        self.yaw_rate_dps: float | None = None
        self.relative_yaw_degrees = 0.0
        self.previous_time_ns: int | None = None
        self.previous_rate_dps: float | None = None
        self.sample_count = 0
        self.captured_at = 0.0
        self.sensor: ImuSensor | None = None

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.shutdown.set()
        self.thread.join(timeout=2.0)
        if self.sensor is not None:
            self.sensor.close()

    def status(self) -> dict[str, object]:
        with self.lock:
            age_ms = (
                round(max(0.0, self.clock() - self.captured_at) * 1000)
                if self.sample_count
                else None
            )
            return {
                "state": self.state,
                "yaw_rate_dps": (
                    round(self.yaw_rate_dps, 2)
                    if self.yaw_rate_dps is not None
                    else None
                ),
                "relative_yaw_degrees": round(self.relative_yaw_degrees, 1),
                "bias_dps": round(self.bias_dps, 3) if self.bias_dps is not None else None,
                "noise_dps": (
                    round(self.noise_dps, 3) if self.noise_dps is not None else None
                ),
                "sample_age_ms": age_ms,
                "sample_count": self.sample_count,
                "error": self.error,
            }

    def _accept(self, sample: ImuSampleSource) -> None:
        raw_yaw_rate = sample.gyro_dps[1]
        with self.lock:
            self.sample_count += 1
            self.captured_at = self.clock()
            if self.bias_dps is None:
                self.state = "calibrating"
                if self.motors_active():
                    return
                self.bias_samples.append(raw_yaw_rate)
                if len(self.bias_samples) < self.bias_sample_count:
                    return
                self.bias_dps = statistics.fmean(self.bias_samples)
                self.noise_dps = statistics.pstdev(self.bias_samples)
                self.previous_time_ns = sample.timestamp_ns
                self.previous_rate_dps = 0.0
                self.yaw_rate_dps = 0.0
                self.state = "streaming"
                return

            corrected_rate = raw_yaw_rate - self.bias_dps
            if self.previous_time_ns is not None and self.previous_rate_dps is not None:
                dt = (sample.timestamp_ns - self.previous_time_ns) / 1e9
                self.relative_yaw_degrees += (
                    self.previous_rate_dps + corrected_rate
                ) * 0.5 * dt
            self.previous_time_ns = sample.timestamp_ns
            self.previous_rate_dps = corrected_rate
            self.yaw_rate_dps = corrected_rate
            self.state = "streaming"

    def _run(self) -> None:
        try:
            self.sensor = self.sensor_factory()
            self.sensor.configure()
            interval = 1.0 / self.sample_hz
            deadline = self.clock()
            while not self.shutdown.is_set():
                self._accept(self.sensor.sample())
                deadline += interval
                self.shutdown.wait(max(0.0, deadline - self.clock()))
        except Exception as error:
            with self.lock:
                self.state = "error"
                self.error = str(error)


def extract_jpeg_frames(buffer: bytearray) -> list[bytes]:
    """Remove and return every complete JPEG currently in an MJPEG buffer."""
    frames: list[bytes] = []
    while True:
        start = buffer.find(JPEG_START)
        if start < 0:
            if len(buffer) > 1:
                del buffer[:-1]
            break
        if start:
            del buffer[:start]
        end = buffer.find(JPEG_END, len(JPEG_START))
        if end < 0:
            if len(buffer) > MAX_CAMERA_BUFFER_BYTES:
                buffer.clear()
            break
        frame_end = end + len(JPEG_END)
        frames.append(bytes(buffer[:frame_end]))
        del buffer[:frame_end]
    return frames


class CameraCapture:
    """Keep only the newest frame from one long-running rpicam process."""

    def __init__(
        self,
        *,
        command: tuple[str, ...] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.command = command or (
            "/usr/bin/rpicam-vid",
            "--nopreview",
            "--timeout",
            "0",
            "--codec",
            "mjpeg",
            "--quality",
            "70",
            "--width",
            str(CAMERA_WIDTH),
            "--height",
            str(CAMERA_HEIGHT),
            "--framerate",
            str(CAMERA_FRAMERATE),
            "--autofocus-mode",
            "continuous",
            "--output",
            "-",
        )
        self.clock = clock
        self.shutdown = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.lock = threading.Lock()
        self.process: subprocess.Popen[bytes] | None = None
        self.frame: bytes | None = None
        self.frame_id = 0
        self.captured_at = 0.0
        self.frame_times: deque[float] = deque(maxlen=30)
        self.error: str | None = None

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.shutdown.set()
        with self.lock:
            process = self.process
        if process is not None and process.poll() is None:
            process.terminate()
        self.thread.join(timeout=3.0)
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=1.0)

    def latest(self) -> tuple[bytes, int, int] | None:
        with self.lock:
            if self.frame is None:
                return None
            age_ms = round(max(0.0, self.clock() - self.captured_at) * 1000)
            return self.frame, self.frame_id, age_ms

    def status(self) -> dict[str, object]:
        with self.lock:
            frame_times = tuple(self.frame_times)
            frame_age_ms = (
                round(max(0.0, self.clock() - self.captured_at) * 1000)
                if self.frame is not None
                else None
            )
            if len(frame_times) > 1 and frame_times[-1] > frame_times[0]:
                capture_fps = round(
                    (len(frame_times) - 1) / (frame_times[-1] - frame_times[0]), 1
                )
            else:
                capture_fps = 0.0
            running = self.process is not None and self.process.poll() is None
            state = "streaming" if running and frame_age_ms is not None else "starting"
            if not running and self.error:
                state = "error"
            elif frame_age_ms is not None and frame_age_ms > 2000:
                state = "stalled"
            return {
                "state": state,
                "width": CAMERA_WIDTH,
                "height": CAMERA_HEIGHT,
                "capture_fps": capture_fps,
                "frame_age_ms": frame_age_ms,
                "frame_id": self.frame_id,
                "error": self.error,
            }

    def _run(self) -> None:
        while not self.shutdown.is_set():
            try:
                process = subprocess.Popen(
                    self.command,
                    stdout=subprocess.PIPE,
                    stderr=None,
                )
            except OSError as error:
                with self.lock:
                    self.error = str(error)
                self.shutdown.wait(2.0)
                continue

            with self.lock:
                self.process = process
                self.error = None
            buffer = bytearray()
            assert process.stdout is not None
            while not self.shutdown.is_set():
                # Buffered read(size) can wait for several JPEGs to fill size.
                chunk = process.stdout.read1(64 * 1024)
                if not chunk:
                    break
                buffer.extend(chunk)
                for frame in extract_jpeg_frames(buffer):
                    self._publish(frame)

            if process.poll() is None:
                process.terminate()
            try:
                return_code = process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                return_code = process.wait(timeout=1.0)
            process.stdout.close()
            with self.lock:
                self.process = None
                if not self.shutdown.is_set():
                    self.error = f"rpicam exited with status {return_code}"
            self.shutdown.wait(2.0)

    def _publish(self, frame: bytes) -> None:
        captured_at = self.clock()
        with self.lock:
            self.frame = frame
            self.frame_id += 1
            self.captured_at = captured_at
            self.frame_times.append(captured_at)


def unit_float(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return number


def signed_unit_float(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number) or not -1.0 <= number <= 1.0:
        raise ValueError(f"{name} must be between -1 and 1")
    return number


@dataclass(frozen=True)
class MotorCalibration:
    left_pwm: float = STRAIGHT_LEFT_PWM
    right_pwm: float = STRAIGHT_RIGHT_PWM
    turn_pwm: float = TURN_PWM

    def __post_init__(self) -> None:
        object.__setattr__(self, "left_pwm", unit_float("left_pwm", self.left_pwm))
        object.__setattr__(
            self, "right_pwm", unit_float("right_pwm", self.right_pwm)
        )
        object.__setattr__(self, "turn_pwm", unit_float("turn_pwm", self.turn_pwm))

    def as_dict(self) -> dict[str, float]:
        return {
            "left_pwm": self.left_pwm,
            "right_pwm": self.right_pwm,
            "turn_pwm": self.turn_pwm,
        }


class CalibrationStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.calibration = self._load()

    def snapshot(self) -> MotorCalibration:
        with self.lock:
            return self.calibration

    def update(self, left_pwm: object, right_pwm: object) -> MotorCalibration:
        with self.lock:
            calibration = MotorCalibration(
                left_pwm=left_pwm,
                right_pwm=right_pwm,
                turn_pwm=self.calibration.turn_pwm,
            )
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_name(f".{self.path.name}.tmp")
                temporary.write_text(
                    json.dumps(calibration.as_dict(), indent=2) + "\n"
                )
                temporary.chmod(0o600)
                temporary.replace(self.path)
            self.calibration = calibration
            return calibration

    def _load(self) -> MotorCalibration:
        if self.path is None or not self.path.exists():
            return MotorCalibration()
        try:
            payload = json.loads(self.path.read_text())
            if not isinstance(payload, dict):
                raise ValueError("calibration must be an object")
            return MotorCalibration(
                left_pwm=payload.get("left_pwm"),
                right_pwm=payload.get("right_pwm"),
                turn_pwm=payload.get("turn_pwm", TURN_PWM),
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(f"invalid saved calibration; using defaults: {error}")
            return MotorCalibration()


@dataclass(frozen=True)
class HeadingHoldConfig:
    enabled: bool = False
    proportional_gain: float = 0.012
    rate_gain: float = 0.004
    maximum_correction: float = 0.18
    maximum_sample_age_ms: int = 150

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "proportional_gain": self.proportional_gain,
            "rate_gain": self.rate_gain,
            "maximum_correction": self.maximum_correction,
            "maximum_sample_age_ms": self.maximum_sample_age_ms,
        }


class HeadingHoldStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.config = self._load()

    def snapshot(self) -> HeadingHoldConfig:
        with self.lock:
            return self.config

    def update(self, enabled: object) -> HeadingHoldConfig:
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        with self.lock:
            config = HeadingHoldConfig(enabled=enabled)
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_name(f".{self.path.name}.tmp")
                temporary.write_text(json.dumps(config.as_dict(), indent=2) + "\n")
                temporary.chmod(0o600)
                temporary.replace(self.path)
            self.config = config
            return config

    def _load(self) -> HeadingHoldConfig:
        if self.path is None or not self.path.exists():
            return HeadingHoldConfig()
        try:
            payload = json.loads(self.path.read_text())
            if not isinstance(payload, dict) or not isinstance(
                payload.get("enabled"), bool
            ):
                raise ValueError("heading hold must contain a boolean enabled value")
            return HeadingHoldConfig(enabled=payload["enabled"])
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(f"invalid heading-hold setting; using disabled: {error}")
            return HeadingHoldConfig()


def speeds_for(
    motion: str,
    throttle: float = 1.0,
    calibration: MotorCalibration | None = None,
) -> tuple[float, float]:
    throttle_value = unit_float("throttle", throttle)
    current = calibration or MotorCalibration()
    try:
        left, right = {
            "forward": (current.left_pwm, current.right_pwm),
            "reverse": (-current.left_pwm, -current.right_pwm),
            "left": (-current.turn_pwm, current.turn_pwm),
            "right": (current.turn_pwm, -current.turn_pwm),
            "stop": (0.0, 0.0),
        }[motion]
    except KeyError as error:
        raise ValueError(f"invalid motion: {motion}") from error
    return left * throttle_value, right * throttle_value


def speeds_for_action(
    forward: object,
    turn: object,
    calibration: MotorCalibration | None = None,
) -> tuple[float, float]:
    """Mix normalized autonomy actions and apply measured side calibration."""
    forward_value = signed_unit_float("forward", forward)
    turn_value = signed_unit_float("turn", turn)
    left = forward_value + turn_value
    right = forward_value - turn_value
    scale = max(1.0, abs(left), abs(right))
    current = calibration or MotorCalibration()
    return (
        left / scale * current.left_pwm,
        right / scale * current.right_pwm,
    )


class CommandWatchdog:
    """Apply fresh commands continuously and stop stale ones."""

    def __init__(
        self,
        drive: Drive,
        *,
        clock: Callable[[], float] = time.monotonic,
        calibration_store: CalibrationStore | None = None,
        heading_hold_store: HeadingHoldStore | None = None,
    ) -> None:
        self.drive = drive
        self.clock = clock
        self.motion = "stop"
        self.action: tuple[float, float] | None = None
        self.throttle = 1.0
        self.last_command_at = clock()
        self.applied_command: tuple[object, ...] | None = None
        self.applied_speeds = (0.0, 0.0)
        self.calibration_store = calibration_store or CalibrationStore()
        self.heading_hold_store = heading_hold_store or HeadingHoldStore()
        self.heading_source: object | None = None
        self.hold_reference_yaw: float | None = None
        self.hold_measured_yaw: float | None = None
        self.hold_error_degrees: float | None = None
        self.hold_correction = 0.0
        self.hold_saturated = False
        self.hold_state = (
            "ready" if self.heading_hold_store.snapshot().enabled else "disabled"
        )
        self.motor_active = False
        self.stale = False
        self.lock = threading.Lock()

    def attach_heading_source(self, heading_source: object) -> None:
        self.heading_source = heading_source

    def submit(self, motion: str, throttle: float = 1.0) -> None:
        speeds_for(motion, throttle, self.calibration_store.snapshot())
        with self.lock:
            now = self.clock()
            starting_straight_command = (
                motion in {"forward", "reverse"}
                and (self.motion != motion or self.action is not None or not self.motor_active)
            )
            self.motion = motion
            self.action = None
            self.throttle = float(throttle)
            self.last_command_at = now
            self.stale = False
            if starting_straight_command:
                self._reset_heading_hold_locked("ready")
            elif motion not in {"forward", "reverse"}:
                self._reset_heading_hold_locked()
            if motion == "stop":
                self._stop_locked()

    def submit_action(self, forward: object, turn: object) -> None:
        forward_value = signed_unit_float("forward", forward)
        turn_value = signed_unit_float("turn", turn)
        speeds_for_action(
            forward_value,
            turn_value,
            self.calibration_store.snapshot(),
        )
        with self.lock:
            self.throttle = 1.0
            self.last_command_at = self.clock()
            self.stale = False
            if forward_value == 0.0 and turn_value == 0.0:
                self.motion = "stop"
                self.action = None
                self._stop_locked()
                return
            self.motion = "autonomy"
            self.action = (forward_value, turn_value)
            self._reset_heading_hold_locked()

    def tick(self) -> None:
        heading_status = self._heading_status()
        with self.lock:
            now = self.clock()
            age = now - self.last_command_at
            if self.motion == "stop" or age > WATCHDOG_SECONDS:
                self.stale = self.motion != "stop" and age > WATCHDOG_SECONDS
                self._stop_locked()
                return

            calibration = self.calibration_store.snapshot()
            speeds = (
                speeds_for_action(*self.action, calibration)
                if self.action is not None
                else speeds_for(self.motion, self.throttle, calibration)
            )
            if self.action is None and self.motion in {"forward", "reverse"}:
                adjusted = self._apply_heading_hold_locked(speeds, heading_status)
                if adjusted is None:
                    self._stop_locked()
                    return
                speeds = adjusted
            command = (
                self.motion,
                self.throttle,
                calibration,
                self.action,
                round(speeds[0], 4),
                round(speeds[1], 4),
            )
            if self.applied_command != command:
                self.drive.set_tank(*speeds)
                self.applied_speeds = speeds
                self.applied_command = command
                self.motor_active = True

    def status(self) -> dict[str, object]:
        with self.lock:
            if not self.motor_active:
                left, right = 0.0, 0.0
            else:
                left, right = self.applied_speeds
            return {
                "motion": self.motion,
                "motor_active": self.motor_active,
                "stale": self.stale,
                "throttle": round(self.throttle, 2),
                "left_output": round(left, 3),
                "right_output": round(right, 3),
                "action": (
                    {"forward": self.action[0], "turn": self.action[1]}
                    if self.action is not None
                    else None
                ),
                "command_age_ms": round(
                    max(0.0, self.clock() - self.last_command_at) * 1000
                ),
                "heading_hold": self._heading_hold_status_locked(),
            }

    def heading_hold_status(self) -> dict[str, object]:
        with self.lock:
            return self._heading_hold_status_locked()

    def update_heading_hold(self, enabled: object) -> dict[str, object]:
        self.stop()
        config = self.heading_hold_store.update(enabled)
        with self.lock:
            self._reset_heading_hold_locked("ready" if config.enabled else "disabled")
            return self._heading_hold_status_locked()

    def calibration_status(self) -> dict[str, float]:
        return self.calibration_store.snapshot().as_dict()

    def update_calibration(
        self, left_pwm: object, right_pwm: object
    ) -> dict[str, float]:
        self.stop()
        return self.calibration_store.update(left_pwm, right_pwm).as_dict()

    def stop(self) -> None:
        with self.lock:
            self.motion = "stop"
            self.action = None
            self.last_command_at = self.clock()
            self.stale = False
            self._stop_locked()

    def close(self) -> None:
        with self.lock:
            self._stop_locked()
            self.drive.close()

    def _stop_locked(self) -> None:
        self.drive.stop()
        self.applied_command = None
        self.applied_speeds = (0.0, 0.0)
        self.motor_active = False
        if self.motion == "stop" or self.stale:
            self._reset_heading_hold_locked()

    def _heading_status(self) -> dict[str, object] | None:
        source = self.heading_source
        if source is None:
            return None
        try:
            status = source.status()
            return status if isinstance(status, dict) else None
        except Exception:
            return None

    def _apply_heading_hold_locked(
        self,
        speeds: tuple[float, float],
        heading_status: dict[str, object] | None,
    ) -> tuple[float, float] | None:
        config = self.heading_hold_store.snapshot()
        if not config.enabled:
            self._reset_heading_hold_locked("disabled")
            return speeds
        if (
            heading_status is None
            or heading_status.get("state") != "streaming"
            or not isinstance(heading_status.get("relative_yaw_degrees"), (int, float))
            or not isinstance(heading_status.get("yaw_rate_dps"), (int, float))
            or not isinstance(heading_status.get("sample_age_ms"), (int, float))
            or float(heading_status["sample_age_ms"]) > config.maximum_sample_age_ms
        ):
            self.hold_state = "imu_unavailable"
            return None

        measured = float(heading_status["relative_yaw_degrees"])
        yaw_rate = float(heading_status["yaw_rate_dps"])
        if self.hold_reference_yaw is None:
            self.hold_reference_yaw = measured
        error = self.hold_reference_yaw - measured
        unconstrained = (
            config.proportional_gain * error - config.rate_gain * yaw_rate
        )
        correction = max(
            -config.maximum_correction,
            min(config.maximum_correction, unconstrained),
        )
        left = speeds[0] - correction
        right = speeds[1] + correction
        if self.motion == "forward":
            left, right = min(1.0, max(0.0, left)), min(1.0, max(0.0, right))
        else:
            left, right = min(0.0, max(-1.0, left)), min(0.0, max(-1.0, right))

        self.hold_measured_yaw = measured
        self.hold_error_degrees = error
        self.hold_correction = correction
        self.hold_saturated = not math.isclose(correction, unconstrained, abs_tol=1e-9)
        self.hold_state = "holding"
        return left, right

    def _reset_heading_hold_locked(self, state: str | None = None) -> None:
        enabled = self.heading_hold_store.snapshot().enabled
        self.hold_reference_yaw = None
        self.hold_measured_yaw = None
        self.hold_error_degrees = None
        self.hold_correction = 0.0
        self.hold_saturated = False
        self.hold_state = state or ("ready" if enabled else "disabled")

    def _heading_hold_status_locked(self) -> dict[str, object]:
        config = self.heading_hold_store.snapshot()
        return {
            **config.as_dict(),
            "active": self.hold_state == "holding" and self.motor_active,
            "state": self.hold_state,
            "reference_yaw_degrees": (
                round(self.hold_reference_yaw, 1)
                if self.hold_reference_yaw is not None
                else None
            ),
            "measured_yaw_degrees": (
                round(self.hold_measured_yaw, 1)
                if self.hold_measured_yaw is not None
                else None
            ),
            "error_degrees": (
                round(self.hold_error_degrees, 1)
                if self.hold_error_degrees is not None
                else None
            ),
            "correction": round(self.hold_correction, 3),
            "saturated": self.hold_saturated,
        }


def parse_memory_percent(meminfo: str) -> float | None:
    values: dict[str, int] = {}
    for line in meminfo.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        try:
            values[key] = int(value.split()[0])
        except (IndexError, ValueError):
            continue
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if not total or available is None:
        return None
    return round((1.0 - available / total) * 100.0, 1)


def parse_wifi_signal(wireless: str, interface: str = "wlan0") -> int | None:
    for line in wireless.splitlines():
        if not line.lstrip().startswith(f"{interface}:"):
            continue
        fields = line.split()
        try:
            return round(float(fields[3].rstrip(".")))
        except (IndexError, ValueError):
            return None
    return None


def interface_ipv4(interface: str) -> str | None:
    try:
        result = subprocess.run(
            ["/usr/sbin/ip", "-4", "-o", "address", "show", "dev", interface],
            check=True,
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    fields = result.stdout.split()
    try:
        return fields[fields.index("inet") + 1].split("/", 1)[0]
    except (ValueError, IndexError):
        return None


def camera_state(device_tree: Path = Path("/proc/device-tree")) -> str:
    sensor_names = (b"imx708", b"imx219", b"ov5647", b"imx477")
    try:
        compatible_files = device_tree.rglob("compatible")
        for path in compatible_files:
            content = path.read_bytes().lower()
            if any(sensor in content for sensor in sensor_names):
                return "detected"
    except OSError:
        pass
    return "not_detected"


class SystemTelemetry:
    def __init__(
        self,
        camera: CameraFrameSource | None = None,
        imu: ImuMonitor | None = None,
    ) -> None:
        self.detected_camera = camera_state()
        self.camera = camera
        self.imu = imu

    @staticmethod
    def _read(path: Path) -> str | None:
        try:
            return path.read_text().strip()
        except OSError:
            return None

    def status(self) -> dict[str, object]:
        temperature = self._read(Path("/sys/class/thermal/thermal_zone0/temp"))
        uptime = self._read(Path("/proc/uptime"))
        meminfo = self._read(Path("/proc/meminfo"))
        wireless = self._read(Path("/proc/net/wireless"))
        ethernet_carrier = self._read(Path("/sys/class/net/eth0/carrier"))

        try:
            temperature_c = round(int(temperature) / 1000, 1) if temperature else None
        except ValueError:
            temperature_c = None
        try:
            uptime_seconds = round(float(uptime.split()[0])) if uptime else None
        except (ValueError, IndexError):
            uptime_seconds = None

        camera_stream = self.camera.status() if self.camera is not None else None
        return {
            "hostname": socket.gethostname(),
            "uptime_seconds": uptime_seconds,
            "temperature_c": temperature_c,
            "load_1m": round(os.getloadavg()[0], 2),
            "memory_percent": parse_memory_percent(meminfo or ""),
            "wifi_ip": interface_ipv4("wlan0"),
            "wifi_signal_dbm": parse_wifi_signal(wireless or ""),
            "camera_state": self.detected_camera,
            "camera_stream": camera_stream,
            "imu": self.imu.status() if self.imu is not None else None,
            "jetson_state": "linked" if ethernet_carrier == "1" else "offline",
            "power_monitoring": "unavailable",
        }


def confirmed_poweroff(payload: object) -> bool:
    return isinstance(payload, dict) and payload.get("confirm") == "poweroff"


def request_poweroff(path: Path = POWEROFF_REQUEST_PATH) -> None:
    try:
        path.write_text("poweroff\n")
    except OSError as error:
        print(f"poweroff request failed: {error}")


class ControlLoop:
    def __init__(self, watchdog: CommandWatchdog) -> None:
        self.watchdog = watchdog
        self.shutdown = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.shutdown.set()
        self.thread.join(timeout=1.0)
        self.watchdog.close()

    def _run(self) -> None:
        while not self.shutdown.wait(0.01):
            self.watchdog.tick()


def make_handler(
    watchdog: CommandWatchdog,
    ui_path: Path,
    telemetry: SystemTelemetry,
    camera: CameraFrameSource | None = None,
    poweroff_path: Path = POWEROFF_REQUEST_PATH,
    heading: object | None = None,
):
    class RemoteHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            request = urlsplit(self.path)
            if request.path == "/":
                self._send(HTTPStatus.OK, ui_path.read_bytes(), "text/html; charset=utf-8")
            elif request.path == "/api/status":
                self._json(HTTPStatus.OK, watchdog.status())
            elif request.path == "/api/calibration":
                self._json(HTTPStatus.OK, watchdog.calibration_status())
            elif request.path == "/api/heading-hold":
                self._json(HTTPStatus.OK, watchdog.heading_hold_status())
            elif request.path == "/api/telemetry":
                self._json(HTTPStatus.OK, telemetry.status())
            elif request.path == "/api/heading":
                if heading is None:
                    self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "heading control unavailable"})
                else:
                    self._json(HTTPStatus.OK, heading.status())
            elif request.path == "/api/camera/frame.jpg":
                self._camera_frame(parse_qs(request.query))
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:
            try:
                body = self._read_json()
            except (ValueError, json.JSONDecodeError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                return

            if self.path == "/api/command":
                motion = body.get("motion") if isinstance(body, dict) else None
                throttle = body.get("throttle", 1.0) if isinstance(body, dict) else 1.0
                if not isinstance(motion, str):
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "motion must be a string"})
                    return
                try:
                    if heading is not None:
                        heading.cancel("manual command")
                    watchdog.submit(motion, throttle)
                except ValueError as error:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                    return
                self._json(HTTPStatus.OK, watchdog.status())
                return

            if self.path == "/api/action":
                if not isinstance(body, dict):
                    self._json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": "action must be an object"},
                    )
                    return
                try:
                    if heading is not None:
                        heading.cancel("autonomy command")
                    watchdog.submit_action(body.get("forward"), body.get("turn"))
                except ValueError as error:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                    return
                self._json(HTTPStatus.OK, watchdog.status())
                return

            if self.path == "/api/heading/turn":
                if heading is None:
                    self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "heading control unavailable"})
                    return
                if not isinstance(body, dict):
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "turn request must be an object"})
                    return
                try:
                    result = heading.start(body.get("target_degrees"))
                except ValueError as error:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                    return
                except RuntimeError as error:
                    self._json(HTTPStatus.CONFLICT, {"error": str(error)})
                    return
                self._json(HTTPStatus.ACCEPTED, result)
                return

            if self.path == "/api/heading/cancel":
                if heading is None:
                    self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "heading control unavailable"})
                    return
                self._json(HTTPStatus.OK, heading.cancel())
                return

            if self.path == "/api/calibration":
                if not isinstance(body, dict):
                    self._json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": "calibration must be an object"},
                    )
                    return
                try:
                    calibration = watchdog.update_calibration(
                        body.get("left_pwm"), body.get("right_pwm")
                    )
                except ValueError as error:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                    return
                except OSError as error:
                    self._json(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        {"error": f"could not save calibration: {error}"},
                    )
                    return
                self._json(HTTPStatus.OK, calibration)
                return

            if self.path == "/api/heading-hold":
                if not isinstance(body, dict):
                    self._json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": "heading hold setting must be an object"},
                    )
                    return
                try:
                    status = watchdog.update_heading_hold(body.get("enabled"))
                except ValueError as error:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                    return
                except OSError as error:
                    self._json(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        {"error": f"could not save heading hold: {error}"},
                    )
                    return
                self._json(HTTPStatus.OK, status)
                return

            if self.path == "/api/system/shutdown":
                if not confirmed_poweroff(body):
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "confirmation required"})
                    return
                watchdog.stop()
                self._json(HTTPStatus.ACCEPTED, {"status": "shutting_down"})
                timer = threading.Timer(0.5, request_poweroff, args=(poweroff_path,))
                timer.daemon = True
                timer.start()
                return

            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def log_message(self, format_string: str, *args: object) -> None:
            print(f"{self.address_string()} - {format_string % args}")

        def _json(self, status: HTTPStatus, payload: object) -> None:
            self._send(
                status,
                json.dumps(payload, separators=(",", ":")).encode(),
                "application/json",
            )

        def _camera_frame(self, query: dict[str, list[str]]) -> None:
            latest = camera.latest() if camera is not None else None
            if latest is None:
                self._json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": "camera frame unavailable"},
                )
                return
            frame, frame_id, age_ms = latest
            try:
                after = int(query.get("after", ["-1"])[0])
            except ValueError:
                after = -1
            # A client can be ahead when this process restarts and its counter
            # returns to zero. Only equality means the client has this frame.
            if frame_id == after:
                self._send(HTTPStatus.NO_CONTENT, b"", "image/jpeg")
                return
            self._send(
                HTTPStatus.OK,
                frame,
                "image/jpeg",
                {
                    "X-Frame-Id": str(frame_id),
                    "X-Frame-Age-Ms": str(age_ms),
                },
            )

        def _read_json(self) -> object:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 1024:
                raise ValueError("invalid request size")
            return json.loads(self.rfile.read(length))

        def _send(
            self,
            status: HTTPStatus,
            body: bytes,
            content_type: str,
            headers: dict[str, str] | None = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            if body:
                self.wfile.write(body)

    return RemoteHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--ui",
        type=Path,
        default=Path(__file__).parents[1] / "operator-ui" / "index.html",
    )
    parser.add_argument(
        "--calibration",
        type=Path,
        default=DEFAULT_CALIBRATION_PATH,
    )
    parser.add_argument(
        "--heading-hold",
        type=Path,
        default=DEFAULT_HEADING_HOLD_PATH,
    )
    return parser.parse_args()


def main() -> int:
    from gpiozero.pins.lgpio import LGPIOFactory

    from drive import build_drive
    from heading_control import HeadingTurnManager
    from imu import LinuxI2C, MPU9250

    args = parse_args()
    factory = LGPIOFactory(chip=0)
    watchdog = CommandWatchdog(
        build_drive(factory),
        calibration_store=CalibrationStore(args.calibration),
        heading_hold_store=HeadingHoldStore(args.heading_hold),
    )
    camera = CameraCapture()
    imu = ImuMonitor(
        lambda: MPU9250(LinuxI2C("/dev/i2c-1", 0x68)),
        motors_active=lambda: bool(watchdog.status()["motor_active"]),
    )
    watchdog.attach_heading_source(imu)
    telemetry = SystemTelemetry(camera, imu)
    heading = HeadingTurnManager(watchdog, imu)
    loop = ControlLoop(watchdog)
    server = ThreadingHTTPServer(
        (args.host, args.port),
        make_handler(watchdog, args.ui, telemetry, camera, heading=heading),
    )

    def request_shutdown(_signum: int, _frame: object) -> None:
        heading.cancel("service stopping")
        watchdog.stop()
        threading.Thread(target=server.shutdown, daemon=True).start()

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, request_shutdown)

    try:
        camera.start()
        imu.start()
        loop.start()
        print(f"remote control listening on http://{args.host}:{args.port}")
        server.serve_forever()
    finally:
        server.server_close()
        heading.close()
        camera.close()
        imu.close()
        loop.close()
        factory.close()
        print("remote control stopped; motor outputs are low")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
