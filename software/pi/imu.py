#!/usr/bin/env python3
"""Read physical units from an MPU-9250 over Linux I2C."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import fcntl
import os
import statistics
import struct
import time
from typing import Protocol


I2C_SLAVE = 0x0703
WHO_AM_I = 0x75
EXPECTED_IDENTITY = 0x71
PWR_MGMT_1 = 0x6B
SMPLRT_DIV = 0x19
CONFIG = 0x1A
GYRO_CONFIG = 0x1B
ACCEL_CONFIG = 0x1C
ACCEL_CONFIG_2 = 0x1D
ACCEL_XOUT_H = 0x3B
ACCEL_LSB_PER_G = 16384.0
GYRO_LSB_PER_DPS = 131.0


class RegisterBus(Protocol):
    def read(self, register: int, length: int) -> bytes: ...
    def write(self, register: int, value: int) -> None: ...
    def close(self) -> None: ...


class LinuxI2C:
    """Minimal Linux i2c-dev adapter with no third-party dependency."""

    def __init__(self, device: str, address: int) -> None:
        self.fd = os.open(device, os.O_RDWR)
        fcntl.ioctl(self.fd, I2C_SLAVE, address)

    def read(self, register: int, length: int) -> bytes:
        os.write(self.fd, bytes((register,)))
        data = os.read(self.fd, length)
        if len(data) != length:
            raise OSError(f"expected {length} I2C bytes, received {len(data)}")
        return data

    def write(self, register: int, value: int) -> None:
        os.write(self.fd, bytes((register, value)))

    def close(self) -> None:
        os.close(self.fd)


@dataclass(frozen=True)
class ImuSample:
    timestamp_ns: int
    accel_g: tuple[float, float, float]
    gyro_dps: tuple[float, float, float]
    temperature_c: float


class MPU9250:
    def __init__(self, bus: RegisterBus) -> None:
        self.bus = bus

    def identity(self) -> int:
        return self.bus.read(WHO_AM_I, 1)[0]

    def configure(self) -> None:
        identity = self.identity()
        if identity != EXPECTED_IDENTITY:
            raise RuntimeError(
                f"expected MPU-9250 identity 0x{EXPECTED_IDENTITY:02X}, "
                f"received 0x{identity:02X}"
            )

        self.bus.write(PWR_MGMT_1, 0x01)
        time.sleep(0.1)
        self.bus.write(CONFIG, 0x03)
        self.bus.write(SMPLRT_DIV, 0x04)
        self.bus.write(GYRO_CONFIG, 0x00)
        self.bus.write(ACCEL_CONFIG, 0x00)
        self.bus.write(ACCEL_CONFIG_2, 0x03)

    def sample(self, *, timestamp_ns: int | None = None) -> ImuSample:
        raw = struct.unpack(">hhhhhhh", self.bus.read(ACCEL_XOUT_H, 14))
        accel = tuple(value / ACCEL_LSB_PER_G for value in raw[0:3])
        temperature = raw[3] / 333.87 + 21.0
        gyro = tuple(value / GYRO_LSB_PER_DPS for value in raw[4:7])
        return ImuSample(
            timestamp_ns=time.monotonic_ns() if timestamp_ns is None else timestamp_ns,
            accel_g=accel,
            gyro_dps=gyro,
            temperature_c=temperature,
        )

    def close(self) -> None:
        self.bus.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="/dev/i2c-1")
    parser.add_argument("--address", type=lambda value: int(value, 0), default=0x68)
    parser.add_argument("--samples", type=int, default=100)
    parser.add_argument("--rate-hz", type=float, default=20.0)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be at least 1")
    if not 1.0 <= args.rate_hz <= 200.0:
        parser.error("--rate-hz must be between 1 and 200")
    return args


def main() -> int:
    args = parse_args()
    imu = MPU9250(LinuxI2C(args.device, args.address))
    samples: list[ImuSample] = []
    interval = 1.0 / args.rate_hz
    try:
        imu.configure()
        print("time_s,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,temp_c")
        start = time.monotonic()
        deadline = start
        for _ in range(args.samples):
            sample = imu.sample()
            samples.append(sample)
            elapsed = (sample.timestamp_ns / 1e9) - start
            ax, ay, az = sample.accel_g
            gx, gy, gz = sample.gyro_dps
            print(
                f"{elapsed:.6f},{ax:.5f},{ay:.5f},{az:.5f},"
                f"{gx:.3f},{gy:.3f},{gz:.3f},{sample.temperature_c:.2f}"
            )
            deadline += interval
            time.sleep(max(0.0, deadline - time.monotonic()))
    finally:
        imu.close()

    print("gyro_stationary_mean_dps," + ",".join(
        f"{statistics.fmean(sample.gyro_dps[axis] for sample in samples):.3f}"
        for axis in range(3)
    ))
    print("gyro_stationary_stddev_dps," + ",".join(
        f"{statistics.pstdev(sample.gyro_dps[axis] for sample in samples):.3f}"
        for axis in range(3)
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
