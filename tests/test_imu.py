import importlib.util
import pathlib
import struct
import sys
import unittest


MODULE_PATH = pathlib.Path(__file__).parents[1] / "software" / "pi" / "imu.py"
SPEC = importlib.util.spec_from_file_location("imu", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
ACCEL_XOUT_H = MODULE.ACCEL_XOUT_H
MPU9250 = MODULE.MPU9250


class FakeBus:
    def __init__(self, identity=0x71, sample=b"\x00" * 14):
        self.identity_value = identity
        self.sample_value = sample
        self.writes = []
        self.closed = False

    def read(self, register, length):
        if register == MODULE.WHO_AM_I:
            return bytes((self.identity_value,))
        if register == ACCEL_XOUT_H:
            return self.sample_value
        raise AssertionError(f"unexpected register 0x{register:02X}")

    def write(self, register, value):
        self.writes.append((register, value))

    def close(self):
        self.closed = True


class MPU9250Test(unittest.TestCase):
    def test_configure_checks_identity_and_sets_known_ranges(self):
        bus = FakeBus()
        sensor = MPU9250(bus)

        sensor.configure()

        self.assertEqual(
            bus.writes,
            [
                (MODULE.PWR_MGMT_1, 0x01),
                (MODULE.CONFIG, 0x03),
                (MODULE.SMPLRT_DIV, 0x04),
                (MODULE.GYRO_CONFIG, 0x00),
                (MODULE.ACCEL_CONFIG, 0x00),
                (MODULE.ACCEL_CONFIG_2, 0x03),
            ],
        )

    def test_sample_converts_signed_registers_to_physical_units(self):
        bus = FakeBus(
            sample=struct.pack(
                ">hhhhhhh",
                16384,
                -8192,
                4096,
                0,
                131,
                -262,
                0,
            )
        )
        sample = MPU9250(bus).sample(timestamp_ns=123)

        self.assertEqual(sample.timestamp_ns, 123)
        self.assertEqual(sample.accel_g, (1.0, -0.5, 0.25))
        self.assertEqual(sample.gyro_dps, (1.0, -2.0, 0.0))
        self.assertAlmostEqual(sample.temperature_c, 21.0)

    def test_wrong_identity_is_rejected_before_configuration(self):
        bus = FakeBus(identity=0x70)

        with self.assertRaisesRegex(RuntimeError, "received 0x70"):
            MPU9250(bus).configure()


if __name__ == "__main__":
    unittest.main()
