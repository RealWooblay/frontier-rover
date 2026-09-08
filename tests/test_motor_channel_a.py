import importlib.util
import pathlib
import unittest


MODULE_PATH = (
    pathlib.Path(__file__).parents[1] / "software" / "pi" / "motor_channel_a.py"
)
SPEC = importlib.util.spec_from_file_location("motor_channel_a", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
TB6612Channel = MODULE.TB6612Channel


class FakeOutput:
    def __init__(self) -> None:
        self.value = 0.0
        self.closed = False

    def on(self) -> None:
        self.value = 1.0

    def off(self) -> None:
        self.value = 0.0

    def close(self) -> None:
        self.closed = True


class TB6612ChannelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.in1 = FakeOutput()
        self.in2 = FakeOutput()
        self.pwm = FakeOutput()
        self.standby = FakeOutput()
        self.motor = TB6612Channel(
            self.in1, self.in2, self.pwm, self.standby
        )

    def test_forward_sets_direction_speed_and_standby(self) -> None:
        self.motor.drive("forward", 0.4)
        self.assertEqual(self.in1.value, 1.0)
        self.assertEqual(self.in2.value, 0.0)
        self.assertEqual(self.pwm.value, 0.4)
        self.assertEqual(self.standby.value, 1.0)

    def test_reverse_sets_opposite_direction(self) -> None:
        self.motor.drive("reverse", 0.7)
        self.assertEqual(self.in1.value, 0.0)
        self.assertEqual(self.in2.value, 1.0)
        self.assertEqual(self.pwm.value, 0.7)
        self.assertEqual(self.standby.value, 1.0)

    def test_close_stops_and_closes_every_output(self) -> None:
        self.motor.drive("forward", 1.0)
        self.motor.close()
        for output in (self.in1, self.in2, self.pwm, self.standby):
            self.assertEqual(output.value, 0.0)
            self.assertTrue(output.closed)


if __name__ == "__main__":
    unittest.main()
