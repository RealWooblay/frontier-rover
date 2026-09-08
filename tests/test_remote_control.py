import http.client
import importlib.util
import json
import pathlib
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer


MODULE_PATH = pathlib.Path(__file__).parents[1] / "software" / "pi" / "remote_control.py"
SPEC = importlib.util.spec_from_file_location("remote_control", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
CommandWatchdog = MODULE.CommandWatchdog
CalibrationStore = MODULE.CalibrationStore
HeadingHoldStore = MODULE.HeadingHoldStore
ImuMonitor = MODULE.ImuMonitor
MotorCalibration = MODULE.MotorCalibration
extract_jpeg_frames = MODULE.extract_jpeg_frames
make_handler = MODULE.make_handler
confirmed_poweroff = MODULE.confirmed_poweroff
parse_memory_percent = MODULE.parse_memory_percent
parse_wifi_signal = MODULE.parse_wifi_signal
request_poweroff = MODULE.request_poweroff
speeds_for = MODULE.speeds_for
speeds_for_action = MODULE.speeds_for_action


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakeDrive:
    def __init__(self) -> None:
        self.commands = []
        self.closed = False

    def set_tank(self, left_speed: float, right_speed: float) -> None:
        self.commands.append((left_speed, right_speed))

    def stop(self) -> None:
        self.commands.append((0.0, 0.0))

    def close(self) -> None:
        self.closed = True


class FakeCamera:
    def __init__(self, frame: bytes | None = b"\xff\xd8camera\xff\xd9") -> None:
        self.frame = frame

    def latest(self) -> tuple[bytes, int, int] | None:
        return (self.frame, 7, 42) if self.frame is not None else None

    def status(self) -> dict[str, object]:
        return {"state": "streaming", "capture_fps": 15.0, "frame_age_ms": 42}


class FakeImuSample:
    def __init__(self, timestamp_ns: int, yaw_rate_dps: float) -> None:
        self.timestamp_ns = timestamp_ns
        self.gyro_dps = (0.0, yaw_rate_dps, 0.0)


class FakeHeading:
    def __init__(self) -> None:
        self.cancelled = 0
        self.target = None

    def status(self):
        return {"state": "idle", "active": False, "target_degrees": self.target}

    def start(self, target):
        if target is None:
            raise ValueError("target_degrees must be a number")
        self.target = float(target)
        return {"state": "turning", "active": True, "target_degrees": self.target}

    def cancel(self, _message="cancelled"):
        self.cancelled += 1
        return {"state": "cancelled", "active": False, "target_degrees": self.target}


class FakeImuHeading:
    def __init__(self, yaw=0.0, yaw_rate=0.0, age_ms=5, state="streaming"):
        self.yaw = yaw
        self.yaw_rate = yaw_rate
        self.age_ms = age_ms
        self.state = state

    def status(self):
        return {
            "state": self.state,
            "relative_yaw_degrees": self.yaw,
            "yaw_rate_dps": self.yaw_rate,
            "sample_age_ms": self.age_ms,
        }


class CameraFrameParserTest(unittest.TestCase):
    def test_extracts_fragmented_and_consecutive_jpegs(self) -> None:
        buffer = bytearray(b"noise\xff\xd8one")
        self.assertEqual(extract_jpeg_frames(buffer), [])
        buffer.extend(b"\xff\xd9\xff\xd8two\xff\xd9tail")

        self.assertEqual(
            extract_jpeg_frames(buffer),
            [b"\xff\xd8one\xff\xd9", b"\xff\xd8two\xff\xd9"],
        )
        self.assertEqual(buffer, bytearray(b"l"))


class CameraCaptureStreamingTest(unittest.TestCase):
    def test_short_frame_is_published_before_producer_closes(self):
        published = threading.Event()

        class CaptureProbe(MODULE.CameraCapture):
            def _publish(self, frame):
                super()._publish(frame)
                published.set()

        frame = b"\xff\xd8small classroom frame\xff\xd9"
        producer = (
            "import sys,time; "
            f"sys.stdout.buffer.write({frame!r}); "
            "sys.stdout.buffer.flush(); time.sleep(30)"
        )
        capture = CaptureProbe(command=(sys.executable, "-u", "-c", producer))
        capture.start()
        try:
            self.assertTrue(published.wait(2), "reader buffered a complete small frame")
            self.assertEqual(capture.latest()[0], frame)
            self.assertIsNone(capture.process.poll())
        finally:
            capture.close()


class CommandWatchdogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.drive = FakeDrive()
        self.watchdog = CommandWatchdog(self.drive, clock=self.clock)

    def test_calibrated_motion_mapping(self) -> None:
        self.assertEqual(speeds_for("forward"), (0.40, 0.60))
        self.assertEqual(speeds_for("reverse"), (-0.40, -0.60))
        self.assertEqual(speeds_for("left"), (-0.50, 0.50))
        self.assertEqual(speeds_for("right"), (0.50, -0.50))

    def test_throttle_scales_calibration(self) -> None:
        self.assertEqual(speeds_for("forward", 0.5), (0.20, 0.30))
        self.assertEqual(speeds_for("left", 0.5), (-0.25, 0.25))

    def test_custom_calibration_changes_straight_output(self) -> None:
        calibration = MotorCalibration(left_pwm=0.25, right_pwm=0.75)
        self.assertEqual(
            speeds_for("forward", 1.0, calibration),
            (0.25, 0.75),
        )
        self.assertEqual(
            speeds_for("reverse", 0.5, calibration),
            (-0.125, -0.375),
        )

    def test_command_stays_active_while_fresh(self) -> None:
        self.watchdog.submit("forward")
        self.watchdog.tick()
        self.assertEqual(self.drive.commands[-1], (0.40, 0.60))
        self.clock.now = 0.11
        self.watchdog.tick()
        self.assertEqual(self.drive.commands[-1], (0.40, 0.60))

    def test_heartbeat_does_not_reapply_gpio_command(self) -> None:
        self.watchdog.submit("forward")
        self.watchdog.tick()
        command_count = len(self.drive.commands)
        self.clock.now = 0.09
        self.watchdog.submit("forward")
        self.clock.now = 0.11
        self.watchdog.tick()
        self.assertEqual(len(self.drive.commands), command_count)

    def test_throttle_change_reapplies_gpio_command(self) -> None:
        self.watchdog.submit("forward", 0.5)
        self.watchdog.tick()
        self.assertEqual(self.drive.commands[-1], (0.20, 0.30))
        self.watchdog.submit("forward", 0.75)
        self.watchdog.tick()
        left, right = self.drive.commands[-1]
        self.assertAlmostEqual(left, 0.30)
        self.assertAlmostEqual(right, 0.45)

    def test_direction_change_is_applied(self) -> None:
        self.watchdog.submit("forward")
        self.watchdog.tick()
        self.watchdog.submit("reverse")
        self.watchdog.tick()
        self.assertEqual(self.drive.commands[-1], (-0.40, -0.60))

    def test_stale_command_stops(self) -> None:
        self.watchdog.submit("forward")
        self.watchdog.tick()
        self.clock.now = 0.36
        self.watchdog.tick()
        self.assertEqual(self.drive.commands[-1], (0.0, 0.0))
        self.assertTrue(self.watchdog.status()["stale"])

    def test_stop_command_is_immediate(self) -> None:
        self.watchdog.submit("reverse")
        self.watchdog.tick()
        self.watchdog.submit("stop")
        self.assertEqual(self.drive.commands[-1], (0.0, 0.0))
        self.assertEqual(self.watchdog.status()["motion"], "stop")

    def test_invalid_command_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.watchdog.submit("launch")

    def test_invalid_throttle_is_rejected(self) -> None:
        for throttle in (-0.1, 1.1, float("nan"), True, "fast"):
            with self.subTest(throttle=throttle), self.assertRaises(ValueError):
                self.watchdog.submit("forward", throttle)

    def test_continuous_action_is_mixed_and_calibrated(self) -> None:
        self.watchdog.submit_action(0.4, 0.2)
        self.watchdog.tick()
        left, right = self.drive.commands[-1]
        self.assertAlmostEqual(left, 0.24)
        self.assertAlmostEqual(right, 0.12)
        self.assertEqual(
            self.watchdog.status()["action"],
            {"forward": 0.4, "turn": 0.2},
        )

    def test_continuous_action_is_bounded(self) -> None:
        self.assertEqual(speeds_for_action(1.0, 1.0), (0.4, 0.0))
        for value in (-1.1, 1.1, float("nan"), True, "fast", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.watchdog.submit_action(value, 0.0)

    def test_stale_continuous_action_stops(self) -> None:
        self.watchdog.submit_action(0.3, 0.1)
        self.watchdog.tick()
        self.clock.now = 0.36
        self.watchdog.tick()
        self.assertEqual(self.drive.commands[-1], (0.0, 0.0))
        self.assertTrue(self.watchdog.status()["stale"])

    def test_zero_continuous_action_is_an_immediate_stop(self) -> None:
        self.watchdog.submit_action(0.3, 0.1)
        self.watchdog.tick()
        self.watchdog.submit_action(0.0, 0.0)
        status = self.watchdog.status()
        self.assertEqual(self.drive.commands[-1], (0.0, 0.0))
        self.assertEqual(status["motion"], "stop")
        self.assertIsNone(status["action"])
        self.assertFalse(status["motor_active"])

    def test_status_reports_applied_outputs(self) -> None:
        self.watchdog.submit("forward", 0.5)
        self.watchdog.tick()
        status = self.watchdog.status()
        self.assertEqual(status["throttle"], 0.5)
        self.assertEqual(status["left_output"], 0.2)
        self.assertEqual(status["right_output"], 0.3)

    def test_calibration_update_stops_active_motors(self) -> None:
        self.watchdog.submit("forward")
        self.watchdog.tick()
        calibration = self.watchdog.update_calibration(0.5, 0.7)
        self.assertEqual(self.drive.commands[-1], (0.0, 0.0))
        self.assertFalse(self.watchdog.status()["motor_active"])
        self.assertEqual(calibration["left_pwm"], 0.5)
        self.assertEqual(calibration["right_pwm"], 0.7)

    def test_heading_hold_corrects_left_drift_without_resetting_on_heartbeat(self) -> None:
        hold_store = HeadingHoldStore()
        hold_store.update(True)
        watchdog = CommandWatchdog(
            self.drive,
            clock=self.clock,
            heading_hold_store=hold_store,
        )
        imu = FakeImuHeading(yaw=10.0)
        watchdog.attach_heading_source(imu)

        watchdog.submit("forward")
        watchdog.tick()
        self.assertEqual(self.drive.commands[-1], (0.4, 0.6))

        imu.yaw = 15.0
        imu.yaw_rate = 5.0
        self.clock.now = 0.1
        watchdog.submit("forward")
        watchdog.tick()

        left, right = self.drive.commands[-1]
        self.assertGreater(left, 0.4)
        self.assertLess(right, 0.6)
        status = watchdog.heading_hold_status()
        self.assertEqual(status["reference_yaw_degrees"], 10.0)
        self.assertEqual(status["error_degrees"], -5.0)
        self.assertLess(status["correction"], 0.0)

    def test_heading_hold_uses_the_same_heading_correction_while_reversing(self) -> None:
        hold_store = HeadingHoldStore()
        hold_store.update(True)
        watchdog = CommandWatchdog(
            self.drive,
            clock=self.clock,
            heading_hold_store=hold_store,
        )
        imu = FakeImuHeading(yaw=0.0)
        watchdog.attach_heading_source(imu)
        watchdog.submit("reverse")
        watchdog.tick()

        imu.yaw = 5.0
        imu.yaw_rate = 4.0
        self.clock.now = 0.1
        watchdog.submit("reverse")
        watchdog.tick()

        left, right = self.drive.commands[-1]
        self.assertGreater(left, -0.4)
        self.assertLess(right, -0.6)

    def test_heading_hold_stops_when_imu_data_is_stale(self) -> None:
        hold_store = HeadingHoldStore()
        hold_store.update(True)
        watchdog = CommandWatchdog(
            self.drive,
            clock=self.clock,
            heading_hold_store=hold_store,
        )
        watchdog.attach_heading_source(FakeImuHeading(age_ms=500))

        watchdog.submit("forward")
        watchdog.tick()

        self.assertEqual(self.drive.commands[-1], (0.0, 0.0))
        self.assertFalse(watchdog.status()["motor_active"])
        self.assertEqual(
            watchdog.heading_hold_status()["state"], "imu_unavailable"
        )


class CalibrationStoreTest(unittest.TestCase):
    def test_update_persists_across_store_reload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "motor-calibration.json"
            store = CalibrationStore(path)
            store.update(0.45, 0.65)

            loaded = CalibrationStore(path).snapshot()

            self.assertEqual(loaded.left_pwm, 0.45)
            self.assertEqual(loaded.right_pwm, 0.65)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_invalid_update_does_not_replace_calibration(self) -> None:
        store = CalibrationStore()
        with self.assertRaises(ValueError):
            store.update(1.1, 0.6)
        self.assertEqual(store.snapshot(), MotorCalibration())


class HeadingHoldStoreTest(unittest.TestCase):
    def test_enabled_setting_persists_across_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "heading-hold.json"
            HeadingHoldStore(path).update(True)

            loaded = HeadingHoldStore(path).snapshot()

            self.assertTrue(loaded.enabled)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


class TelemetryParserTest(unittest.TestCase):
    def test_memory_percent_uses_available_memory(self) -> None:
        meminfo = "MemTotal: 1000 kB\nMemAvailable: 750 kB\n"
        self.assertEqual(parse_memory_percent(meminfo), 25.0)

    def test_missing_memory_values_return_none(self) -> None:
        self.assertIsNone(parse_memory_percent("MemTotal: 1000 kB\n"))

    def test_wifi_signal_reads_requested_interface(self) -> None:
        wireless = "Inter-| sta\n wlan0: 0000 48. -62. -256 0 0 0\n"
        self.assertEqual(parse_wifi_signal(wireless), -62)


class ImuMonitorTest(unittest.TestCase):
    def test_calibrates_bias_then_integrates_corrected_yaw(self) -> None:
        clock = FakeClock()
        monitor = ImuMonitor(lambda: None, clock=clock, bias_sample_count=3)
        for timestamp_ns in (0, 1_000_000_000, 2_000_000_000):
            monitor._accept(FakeImuSample(timestamp_ns, 1.0))

        clock.now = 3.0
        monitor._accept(FakeImuSample(3_000_000_000, 11.0))
        clock.now = 4.0
        monitor._accept(FakeImuSample(4_000_000_000, 11.0))
        status = monitor.status()

        self.assertEqual(status["state"], "streaming")
        self.assertEqual(status["bias_dps"], 1.0)
        self.assertEqual(status["yaw_rate_dps"], 10.0)
        self.assertEqual(status["relative_yaw_degrees"], 15.0)

    def test_does_not_collect_bias_while_motors_are_active(self) -> None:
        monitor = ImuMonitor(
            lambda: None,
            motors_active=lambda: True,
            bias_sample_count=1,
        )

        monitor._accept(FakeImuSample(0, 50.0))

        self.assertIsNone(monitor.status()["bias_dps"])


class PoweroffRequestTest(unittest.TestCase):
    def test_confirmation_is_explicit(self) -> None:
        self.assertTrue(confirmed_poweroff({"confirm": "poweroff"}))
        self.assertFalse(confirmed_poweroff({"confirm": "yes"}))
        self.assertFalse(confirmed_poweroff(None))

    def test_request_writes_only_the_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "poweroff"
            request_poweroff(path)
            self.assertEqual(path.read_text(), "poweroff\n")


class CalibrationApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        directory = pathlib.Path(self.temporary_directory.name)
        self.drive = FakeDrive()
        self.watchdog = CommandWatchdog(
            self.drive,
            calibration_store=CalibrationStore(directory / "calibration.json"),
        )
        ui_path = directory / "index.html"
        ui_path.write_text("test")
        telemetry = type("FakeTelemetry", (), {"status": lambda self: {}})()
        self.camera = FakeCamera()
        self.heading = FakeHeading()
        handler = make_handler(
            self.watchdog, ui_path, telemetry, self.camera, heading=self.heading
        )
        handler.log_message = lambda *_args: None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)
        self.temporary_directory.cleanup()

    def request(
        self, method: str, path: str, payload: object | None = None
    ) -> tuple[int, dict[str, object]]:
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=1
        )
        body = json.dumps(payload) if payload is not None else None
        headers = {"Content-Type": "application/json"} if body else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def request_bytes(
        self, path: str
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=1
        )
        connection.request("GET", path)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_calibration_can_be_read_and_updated(self) -> None:
        status, initial = self.request("GET", "/api/calibration")
        self.assertEqual(status, 200)
        self.assertEqual(initial["left_pwm"], 0.4)
        self.assertEqual(initial["right_pwm"], 0.6)

        status, updated = self.request(
            "POST",
            "/api/calibration",
            {"left_pwm": 0.45, "right_pwm": 0.65},
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["left_pwm"], 0.45)
        self.assertEqual(updated["right_pwm"], 0.65)

    def test_invalid_calibration_is_rejected(self) -> None:
        status, payload = self.request(
            "POST",
            "/api/calibration",
            {"left_pwm": -0.1, "right_pwm": 0.6},
        )
        self.assertEqual(status, 400)
        self.assertIn("between 0 and 1", payload["error"])

    def test_heading_hold_can_be_enabled_and_read(self) -> None:
        status, enabled = self.request(
            "POST", "/api/heading-hold", {"enabled": True}
        )
        self.assertEqual(status, 200)
        self.assertTrue(enabled["enabled"])
        self.assertEqual(enabled["state"], "ready")

        status, current = self.request("GET", "/api/heading-hold")
        self.assertEqual(status, 200)
        self.assertTrue(current["enabled"])

    def test_continuous_action_api_reaches_watchdog(self) -> None:
        status, payload = self.request(
            "POST",
            "/api/action",
            {"forward": 0.4, "turn": 0.2},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["motion"], "autonomy")
        self.assertEqual(payload["action"], {"forward": 0.4, "turn": 0.2})

        self.watchdog.tick()
        left, right = self.drive.commands[-1]
        self.assertAlmostEqual(left, 0.24)
        self.assertAlmostEqual(right, 0.12)
        self.assertEqual(self.heading.cancelled, 1)

    def test_heading_turn_api_starts_and_reports_job(self) -> None:
        status, started = self.request(
            "POST", "/api/heading/turn", {"target_degrees": -90}
        )
        self.assertEqual(status, 202)
        self.assertEqual(started["state"], "turning")
        self.assertEqual(started["target_degrees"], -90.0)

        status, current = self.request("GET", "/api/heading")
        self.assertEqual(status, 200)
        self.assertEqual(current["target_degrees"], -90.0)

    def test_heading_turn_api_can_be_cancelled(self) -> None:
        status, payload = self.request("POST", "/api/heading/cancel", {})
        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], "cancelled")

    def test_invalid_continuous_action_api_is_rejected(self) -> None:
        status, payload = self.request(
            "POST",
            "/api/action",
            {"forward": 2.0, "turn": 0.0},
        )
        self.assertEqual(status, 400)
        self.assertIn("between -1 and 1", payload["error"])

    def test_latest_camera_frame_has_sequence_and_age_headers(self) -> None:
        status, headers, body = self.request_bytes("/api/camera/frame.jpg")

        self.assertEqual(status, 200)
        self.assertEqual(headers["X-Frame-Id"], "7")
        self.assertEqual(headers["X-Frame-Age-Ms"], "42")
        self.assertEqual(body, b"\xff\xd8camera\xff\xd9")

    def test_duplicate_camera_frame_returns_no_content(self) -> None:
        status, _headers, body = self.request_bytes(
            "/api/camera/frame.jpg?after=7"
        )

        self.assertEqual(status, 204)
        self.assertEqual(body, b"")

    def test_client_ahead_after_server_restart_receives_current_frame(self) -> None:
        status, headers, body = self.request_bytes(
            "/api/camera/frame.jpg?after=999"
        )

        self.assertEqual(status, 200)
        self.assertEqual(headers["X-Frame-Id"], "7")
        self.assertEqual(body, b"\xff\xd8camera\xff\xd9")

    def test_unavailable_camera_frame_is_reported(self) -> None:
        self.camera.frame = None
        status, _headers, body = self.request_bytes("/api/camera/frame.jpg")

        self.assertEqual(status, 503)
        self.assertIn(b"camera frame unavailable", body)


if __name__ == "__main__":
    unittest.main()
