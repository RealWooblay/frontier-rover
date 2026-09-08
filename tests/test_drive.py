import importlib.util
import pathlib
import unittest


MODULE_PATH = pathlib.Path(__file__).parents[1] / "software" / "pi" / "drive.py"
SPEC = importlib.util.spec_from_file_location("drive", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
DriverBoard = MODULE.DriverBoard
MotorChannel = MODULE.MotorChannel
RoverDrive = MODULE.RoverDrive
speeds_for = MODULE.speeds_for


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


def channel(*, inverted: bool = False):
    outputs = [FakeOutput() for _ in range(3)]
    return MotorChannel(*outputs, inverted=inverted), outputs


class RoverDriveTest(unittest.TestCase):
    def setUp(self) -> None:
        self.front_left, self.front_left_outputs = channel()
        self.back_left, self.back_left_outputs = channel(inverted=True)
        self.back_right, self.back_right_outputs = channel(inverted=True)
        self.front_right, self.front_right_outputs = channel()
        self.left_standby = FakeOutput()
        self.right_standby = FakeOutput()
        self.drive = RoverDrive(
            DriverBoard(self.front_left, self.back_left, self.left_standby),
            DriverBoard(self.back_right, self.front_right, self.right_standby),
        )

    def test_forward_applies_physical_motor_inversions(self) -> None:
        self.drive.set_tank(0.4, 0.4)
        self.assertEqual(self.front_left_outputs[0].value, 1.0)
        self.assertEqual(self.back_left_outputs[1].value, 1.0)
        self.assertEqual(self.back_right_outputs[1].value, 1.0)
        self.assertEqual(self.front_right_outputs[0].value, 1.0)
        for outputs in (
            self.front_left_outputs,
            self.back_left_outputs,
            self.back_right_outputs,
            self.front_right_outputs,
        ):
            self.assertEqual(outputs[2].value, 0.4)
        self.assertEqual(self.left_standby.value, 1.0)
        self.assertEqual(self.right_standby.value, 1.0)

    def test_stop_lowers_every_output(self) -> None:
        self.drive.set_tank(0.7, -0.6)
        self.drive.stop()
        for output in (
            self.front_left_outputs
            + self.back_left_outputs
            + self.back_right_outputs
            + self.front_right_outputs
            + [self.left_standby, self.right_standby]
        ):
            self.assertEqual(output.value, 0.0)

    def test_motion_mapping(self) -> None:
        self.assertEqual(speeds_for("forward", 0.5), (0.5, 0.5))
        self.assertEqual(speeds_for("reverse", 0.5), (-0.5, -0.5))
        self.assertEqual(speeds_for("left", 0.5), (-0.5, 0.5))
        self.assertEqual(speeds_for("right", 0.5), (0.5, -0.5))
        self.assertEqual(speeds_for("stop", 0.5), (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
