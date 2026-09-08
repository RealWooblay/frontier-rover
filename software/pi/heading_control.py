#!/usr/bin/env python3
"""Non-blocking relative-heading control for the persistent Pi service."""

from __future__ import annotations

from dataclasses import dataclass
import math
import threading
import time
from typing import Callable, Protocol


class MotorCommands(Protocol):
    def submit(self, motion: str, throttle: float = 1.0) -> None: ...
    def stop(self) -> None: ...


class HeadingSource(Protocol):
    def status(self) -> dict[str, object]: ...


@dataclass(frozen=True)
class HeadingConfig:
    turn_throttle: float = 0.70
    stop_early_degrees: float = 12.0
    tolerance_degrees: float = 4.0
    settle_seconds: float = 0.25
    command_period_seconds: float = 0.10
    maximum_corrections: int = 8


@dataclass
class HeadingTurnState:
    target_degrees: float
    start_yaw_degrees: float
    started_at: float
    config: HeadingConfig
    state: str = "turning"
    measured_degrees: float = 0.0
    error_degrees: float = 0.0
    corrections: int = 0
    state_deadline: float = 0.0
    finished_at: float | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        self.error_degrees = self.target_degrees

    @staticmethod
    def direction(error_degrees: float) -> str:
        return "left" if error_degrees > 0.0 else "right"

    @staticmethod
    def correction_duration(error_degrees: float) -> float:
        return min(0.15, max(0.05, abs(error_degrees) / 160.0))

    @property
    def active(self) -> bool:
        return self.state in {"turning", "settling", "correcting"}

    def advance(self, yaw_degrees: float, now: float) -> str | None:
        self.measured_degrees = yaw_degrees - self.start_yaw_degrees
        self.error_degrees = self.target_degrees - self.measured_degrees

        if self.state == "turning" and (
            abs(self.error_degrees) <= self.config.stop_early_degrees
            or self.error_degrees * self.target_degrees <= 0.0
        ):
            self.state = "settling"
            self.state_deadline = now + self.config.settle_seconds
            return "stop"

        if self.state == "settling" and now >= self.state_deadline:
            if abs(self.error_degrees) <= self.config.tolerance_degrees:
                self.state = "complete"
                self.finished_at = now
                return "stop"
            self.corrections += 1
            if self.corrections > self.config.maximum_corrections:
                self.state = "failed"
                self.finished_at = now
                self.message = "turn did not converge within correction limit"
                return "stop"
            self.state = "correcting"
            self.state_deadline = now + self.correction_duration(self.error_degrees)
            return self.direction(self.error_degrees)

        if self.state == "correcting" and now >= self.state_deadline:
            self.state = "settling"
            self.state_deadline = now + self.config.settle_seconds
            return "stop"
        return None

    def status(self, now: float) -> dict[str, object]:
        return {
            "state": self.state,
            "active": self.active,
            "target_degrees": round(self.target_degrees, 1),
            "measured_degrees": round(self.measured_degrees, 1),
            "error_degrees": round(self.error_degrees, 1),
            "corrections": self.corrections,
            "elapsed_seconds": round(
                (self.finished_at if self.finished_at is not None else now)
                - self.started_at,
                2,
            ),
            "message": self.message,
        }


class HeadingTurnManager:
    """Own one bounded relative turn while leaving final authority with the watchdog."""

    def __init__(
        self,
        motors: MotorCommands,
        heading: HeadingSource,
        *,
        config: HeadingConfig | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.motors = motors
        self.heading = heading
        self.config = config or HeadingConfig()
        self.clock = clock
        self.lock = threading.Lock()
        self.turn: HeadingTurnState | None = None
        self.cancel_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self, target_degrees: object) -> dict[str, object]:
        if isinstance(target_degrees, bool) or not isinstance(
            target_degrees, (int, float)
        ):
            raise ValueError("target_degrees must be a number")
        target = float(target_degrees)
        if not math.isfinite(target) or target == 0.0 or abs(target) > 180.0:
            raise ValueError("target_degrees must be nonzero and within -180 to 180")

        heading_status = self.heading.status()
        if heading_status.get("state") != "streaming":
            raise RuntimeError("IMU heading is not ready")
        start_yaw = heading_status.get("relative_yaw_degrees")
        if not isinstance(start_yaw, (int, float)):
            raise RuntimeError("IMU heading is unavailable")

        with self.lock:
            if self.turn is not None and self.turn.active:
                raise RuntimeError("a heading turn is already active")
            self.motors.stop()
            self.cancel_event = threading.Event()
            self.turn = HeadingTurnState(target, float(start_yaw), self.clock(), self.config)
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
            return self.turn.status(self.clock())

    def cancel(self, message: str = "cancelled by operator") -> dict[str, object]:
        self.cancel_event.set()
        with self.lock:
            was_active = self.turn is not None and self.turn.active
            if self.turn is not None and self.turn.active:
                self.turn.state = "cancelled"
                self.turn.finished_at = self.clock()
                self.turn.message = message
            status = self._status_locked()
        if was_active:
            self.motors.stop()
        return status

    def close(self) -> None:
        self.cancel("service stopping")
        thread = self.thread
        if thread is not None:
            thread.join(timeout=1.0)

    def status(self) -> dict[str, object]:
        with self.lock:
            return self._status_locked()

    def _status_locked(self) -> dict[str, object]:
        if self.turn is None:
            return {
                "state": "idle",
                "active": False,
                "target_degrees": None,
                "measured_degrees": None,
                "error_degrees": None,
                "corrections": 0,
                "elapsed_seconds": 0.0,
                "message": None,
            }
        return self.turn.status(self.clock())

    def _run(self) -> None:
        next_command = 0.0
        timeout_at = self.clock() + max(
            4.0, abs(self.turn.target_degrees if self.turn else 0.0) / 30.0 + 3.0
        )
        try:
            while not self.cancel_event.wait(0.02):
                now = self.clock()
                heading_status = self.heading.status()
                if heading_status.get("state") != "streaming":
                    raise RuntimeError("IMU stream became unavailable")
                yaw = heading_status.get("relative_yaw_degrees")
                if not isinstance(yaw, (int, float)):
                    raise RuntimeError("IMU heading became unavailable")

                with self.lock:
                    assert self.turn is not None
                    motion = self.turn.advance(float(yaw), now)
                    turn_active = self.turn.active
                    state = self.turn.state
                    current_motion = (
                        self.turn.direction(self.turn.error_degrees)
                        if state in {"turning", "correcting"}
                        else "stop"
                    )

                if motion == "stop":
                    self.motors.stop()
                elif motion is not None:
                    self.motors.submit(motion, self.config.turn_throttle)
                    next_command = now + self.config.command_period_seconds
                elif current_motion != "stop" and now >= next_command:
                    self.motors.submit(current_motion, self.config.turn_throttle)
                    next_command = now + self.config.command_period_seconds

                if not turn_active:
                    return
                if now >= timeout_at:
                    raise TimeoutError("heading turn exceeded its bounded timeout")
        except Exception as error:
            with self.lock:
                if self.turn is not None and self.turn.active:
                    self.turn.state = "failed"
                    self.turn.finished_at = self.clock()
                    self.turn.message = str(error)
        finally:
            self.motors.stop()
