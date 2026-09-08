#!/usr/bin/env python3
"""Run the verified TB6612 channel-A motor for a bounded time."""

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


class TB6612Channel:
    """Control one TB6612 channel, keeping STBY low unless actively running."""

    def __init__(
        self,
        in1: Output,
        in2: Output,
        pwm: Output,
        standby: Output,
    ) -> None:
        self.in1 = in1
        self.in2 = in2
        self.pwm = pwm
        self.standby = standby
        self.stop()

    def drive(self, direction: str, speed: float) -> None:
        self.stop()
        if direction == "forward":
            self.in1.on()
            self.in2.off()
        elif direction == "reverse":
            self.in1.off()
            self.in2.on()
        else:
            raise ValueError(f"unknown direction: {direction}")
        self.standby.on()
        self.pwm.value = speed

    def stop(self) -> None:
        self.pwm.off()
        self.in1.off()
        self.in2.off()
        self.standby.off()

    def close(self) -> None:
        self.stop()
        for output in (self.pwm, self.in1, self.in2, self.standby):
            output.close()


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
    parser.add_argument("direction", choices=("forward", "reverse"))
    parser.add_argument("--speed", type=bounded_float(0.0, 1.0), default=0.5)
    parser.add_argument("--seconds", type=bounded_float(0.0, 10.0), default=1.0)
    return parser.parse_args()


def stop_on_signal(signum: int, _frame: object) -> None:
    raise SystemExit(128 + signum)


def main() -> int:
    from gpiozero import DigitalOutputDevice, PWMOutputDevice
    from gpiozero.pins.lgpio import LGPIOFactory

    args = parse_args()
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, stop_on_signal)

    factory = LGPIOFactory(chip=0)
    standby = DigitalOutputDevice(25, initial_value=False, pin_factory=factory)
    in1 = DigitalOutputDevice(5, initial_value=False, pin_factory=factory)
    in2 = DigitalOutputDevice(6, initial_value=False, pin_factory=factory)
    pwm = PWMOutputDevice(
        12,
        initial_value=0.0,
        frequency=1000,
        pin_factory=factory,
    )
    motor = TB6612Channel(in1, in2, pwm, standby)

    try:
        print(
            f"channel A: {args.direction} at {args.speed:.0%} "
            f"for {args.seconds:.2f} seconds"
        )
        motor.drive(args.direction, args.speed)
        time.sleep(args.seconds)
    finally:
        motor.close()
        factory.close()
        print("channel A: stopped; PWM, direction, and STBY are low")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
