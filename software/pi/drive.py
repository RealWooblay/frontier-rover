#!/usr/bin/env python3
"""Run a bounded four-motor rover movement using two TB6612 boards."""

from __future__ import annotations

import argparse
import signal
import time
from typing import Protocol

class Output(Protocol):
    value: float

    def on(self) -> None: ...
    def off(self) -> None: ...
    def close(self) -> None: ...


class MotorChannel:
    def __init__(
        self,
        in1: Output,
        in2: Output,
        pwm: Output,
        *,
        inverted: bool = False,
    ) -> None:
        self.in1 = in1
        self.in2 = in2
        self.pwm = pwm
        self.inverted = inverted
        self.stop()

    def prepare(self, speed: float) -> None:
        self.stop()
        effective_speed = -speed if self.inverted else speed
        if effective_speed > 0:
            self.in1.on()
        elif effective_speed < 0:
            self.in2.on()
        self.pwm.value = abs(effective_speed)

    def stop(self) -> None:
        self.pwm.off()
        self.in1.off()
        self.in2.off()

    def close(self) -> None:
        self.stop()
        self.pwm.close()
        self.in1.close()
        self.in2.close()


class DriverBoard:
    def __init__(
        self,
        channel_a: MotorChannel,
        channel_b: MotorChannel,
        standby: Output,
    ) -> None:
        self.channel_a = channel_a
        self.channel_b = channel_b
        self.standby = standby
        self.stop()

    def prepare(self, speed_a: float, speed_b: float) -> None:
        self.standby.off()
        self.channel_a.prepare(speed_a)
        self.channel_b.prepare(speed_b)

    def enable_if_needed(self, speed_a: float, speed_b: float) -> None:
        if speed_a or speed_b:
            self.standby.on()

    def stop(self) -> None:
        self.standby.off()
        self.channel_a.stop()
        self.channel_b.stop()

    def close(self) -> None:
        self.stop()
        self.channel_a.close()
        self.channel_b.close()
        self.standby.close()


class RoverDrive:
    def __init__(self, left: DriverBoard, right: DriverBoard) -> None:
        self.left = left
        self.right = right
        self.stop()

    def set_tank(self, left_speed: float, right_speed: float) -> None:
        if not -1.0 <= left_speed <= 1.0:
            raise ValueError("left speed must be between -1 and 1")
        if not -1.0 <= right_speed <= 1.0:
            raise ValueError("right speed must be between -1 and 1")

        self.stop()
        self.left.prepare(left_speed, left_speed)
        self.right.prepare(right_speed, right_speed)
        self.left.enable_if_needed(left_speed, left_speed)
        self.right.enable_if_needed(right_speed, right_speed)

    def stop(self) -> None:
        self.left.stop()
        self.right.stop()

    def close(self) -> None:
        self.stop()
        self.left.close()
        self.right.close()


def bounded_float(minimum: float, maximum: float):
    def parse(value: str) -> float:
        number = float(value)
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(
                f"must be between {minimum} and {maximum}"
            )
        return number

    return parse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "motion", choices=("forward", "reverse", "left", "right", "stop")
    )
    parser.add_argument("--speed", type=bounded_float(0.0, 1.0), default=0.35)
    parser.add_argument("--seconds", type=bounded_float(0.0, 10.0), default=1.0)
    return parser.parse_args()


def stop_on_signal(signum: int, _frame: object) -> None:
    raise SystemExit(128 + signum)


def digital(pin: int, factory: object) -> Output:
    from gpiozero import DigitalOutputDevice

    return DigitalOutputDevice(pin, initial_value=False, pin_factory=factory)


def pwm(pin: int, factory: object) -> Output:
    from gpiozero import PWMOutputDevice

    return PWMOutputDevice(
        pin,
        initial_value=0.0,
        frequency=1000,
        pin_factory=factory,
    )


def build_drive(factory: object) -> RoverDrive:
    right_standby = digital(25, factory)
    left_standby = digital(24, factory)

    back_right = MotorChannel(
        digital(5, factory),
        digital(6, factory),
        pwm(12, factory),
        inverted=True,
    )
    front_right = MotorChannel(
        digital(16, factory), digital(20, factory), pwm(13, factory)
    )
    front_left = MotorChannel(
        digital(17, factory), digital(27, factory), pwm(18, factory)
    )
    back_left = MotorChannel(
        digital(22, factory),
        digital(23, factory),
        pwm(19, factory),
        inverted=True,
    )

    return RoverDrive(
        left=DriverBoard(front_left, back_left, left_standby),
        right=DriverBoard(back_right, front_right, right_standby),
    )


def speeds_for(motion: str, speed: float) -> tuple[float, float]:
    return {
        "forward": (speed, speed),
        "reverse": (-speed, -speed),
        "left": (-speed, speed),
        "right": (speed, -speed),
        "stop": (0.0, 0.0),
    }[motion]


def main() -> int:
    from gpiozero.pins.lgpio import LGPIOFactory

    args = parse_args()
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, stop_on_signal)

    factory = LGPIOFactory(chip=0)
    drive = build_drive(factory)
    left_speed, right_speed = speeds_for(args.motion, args.speed)

    try:
        print(
            f"{args.motion}: left={left_speed:.0%}, right={right_speed:.0%}, "
            f"duration={args.seconds:.2f}s"
        )
        drive.set_tank(left_speed, right_speed)
        time.sleep(args.seconds)
    finally:
        drive.close()
        factory.close()
        print("stopped: both STBY pins, all PWM, and all direction pins are low")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
