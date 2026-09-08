import importlib.util
from pathlib import Path
import sys
import threading
import time
import unittest


JETSON = Path(__file__).resolve().parents[1] / "software" / "jetson"
sys.path.insert(0, str(JETSON))
MODULE_PATH = JETSON / "autonomy_service.py"
SPEC = importlib.util.spec_from_file_location("autonomy_service", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FakeDetection:
    def __init__(
        self, horizontal_error=0.0, area_ratio=0.02, bottom_edge_ratio=0.5
    ):
        self.horizontal_error = horizontal_error
        self.area_ratio = area_ratio
        self.bottom_edge_ratio = bottom_edge_ratio

    def to_dict(self):
        return {
            "horizontal_error": self.horizontal_error,
            "area_ratio": self.area_ratio,
            "bottom_edge_ratio": self.bottom_edge_ratio,
        }


class FakeDetector:
    def __init__(self, detection=None, error=None):
        self.detection = detection
        self.error = error

    def detect(self, _jpeg):
        if self.error:
            raise self.error
        return self.detection, {"total_ms": 12.0, "inference_ms": 5.0}


class BlockingDetector(FakeDetector):
    def __init__(self):
        super().__init__(FakeDetection())
        self.entered = threading.Event()
        self.release = threading.Event()

    def detect(self, jpeg):
        self.entered.set()
        self.release.wait(1.0)
        return super().detect(jpeg)


class FakeGateway:
    active_url = "http://pi:8765"

    def __init__(self):
        self.actions = []
        self.heading_turns = []
        self.frame_id = 0

    def fetch_frame(self, _after, _timeout):
        self.frame_id += 1
        time.sleep(0.005)
        return b"jpeg", self.frame_id, 5

    def send_action(self, forward, turn, _timeout):
        self.actions.append((forward, turn))
        return 2.5

    def start_heading_turn(self, target_degrees, _timeout):
        self.heading_turns.append(target_degrees)

    def heading_status(self, _timeout):
        return {"active": False, "state": "complete", "message": None}


def wait_for(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition did not become true")


class AutonomyServiceTest(unittest.TestCase):
    def make_service(self, detector):
        gateway = FakeGateway()
        service = MODULE.AutonomyService(gateway, lambda _target, _confidence: detector)
        service.start()
        self.addCleanup(service.close)
        wait_for(lambda: service.status()["detector_ready"])
        return service, gateway

    def test_starts_disarmed_after_detector_load(self):
        service, gateway = self.make_service(FakeDetector())
        status = service.status()
        self.assertEqual(status["state"], "disarmed")
        self.assertFalse(status["armed"])
        self.assertEqual(gateway.actions, [])

    def test_arm_runs_perception_control_and_pi_action(self):
        service, gateway = self.make_service(FakeDetector(FakeDetection()))
        service.arm()
        wait_for(lambda: service.status()["frames_processed"] > 0)
        service.disarm()
        self.assertTrue(any(forward > 0 for forward, _turn in gateway.actions))
        self.assertEqual(gateway.actions[-1], (0.0, 0.0))

    def test_inference_fault_disarms_and_sends_stop(self):
        service, gateway = self.make_service(
            FakeDetector(error=RuntimeError("GPU execution failed"))
        )
        service.arm()
        wait_for(lambda: service.status()["state"] == "fault")
        status = service.status()
        self.assertFalse(status["armed"])
        self.assertIn("GPU execution failed", status["fault"])
        self.assertEqual(gateway.actions[-1], (0.0, 0.0))

    def test_probe_runs_real_control_math_without_sending_action(self):
        service, gateway = self.make_service(
            FakeDetector(FakeDetection(horizontal_error=0.4))
        )
        status = service.probe()
        self.assertEqual(status["state"], "probe_complete")
        self.assertFalse(status["action"]["sent"])
        self.assertGreater(status["action"]["turn"], 0.0)
        self.assertEqual(gateway.actions, [])

    def test_probe_does_not_reuse_arrival_latch_from_previous_mission(self):
        service, gateway = self.make_service(FakeDetector(FakeDetection()))
        service.controller.arrived = True

        status = service.probe()

        self.assertEqual(status["action"]["state"], "approaching")
        self.assertEqual(gateway.actions, [])

    def test_search_observes_three_frames_then_turns_a_measured_angle(self):
        service, gateway = self.make_service(FakeDetector(None))
        service.arm()
        wait_for(lambda: len(gateway.heading_turns) >= 1)
        service.disarm()
        self.assertGreaterEqual(gateway.frame_id, 3)
        self.assertEqual(gateway.heading_turns[0], -30.0)
        self.assertEqual(gateway.actions[-1], (0.0, 0.0))

    def test_monitor_runs_live_inference_without_motor_commands(self):
        service, gateway = self.make_service(FakeDetector(FakeDetection()))
        service.start_monitor()
        wait_for(lambda: service.status()["frames_processed"] > 0)
        status = service.status()
        self.assertTrue(status["monitoring"])
        self.assertEqual(status["state"], "monitoring")
        self.assertEqual(status["perception_source"]["kind"], "live_monitor")
        self.assertEqual(gateway.actions, [])
        service.stop_monitor()
        self.assertFalse(service.status()["monitoring"])

    def test_alignment_uses_a_bounded_motor_pulse(self):
        service, gateway = self.make_service(
            FakeDetector(FakeDetection(horizontal_error=0.5))
        )
        service.arm()
        wait_for(lambda: len(gateway.actions) >= 2)
        service.disarm()
        self.assertEqual(gateway.actions[0], (0.0, 0.3))
        self.assertEqual(gateway.actions[1], (0.0, 0.0))

    def test_completed_search_sweep_reverses_before_searching_again(self):
        service, gateway = self.make_service(FakeDetector(None))
        service.configure({"maximum_search_steps": 4, "maximum_search_cycles": 1})
        service.arm()
        wait_for(lambda: service.status()["search_cycles"] == 1, timeout=2.0)
        service.disarm()
        self.assertIn((-0.35, 0.0), gateway.actions)

    def test_recently_lost_target_holds_still_for_reacquisition(self):
        now = [10.0]
        gateway = FakeGateway()
        service = MODULE.AutonomyService(
            gateway,
            lambda _target, _confidence: FakeDetector(),
            clock=lambda: now[0],
        )
        visible = MODULE.Observation(True, horizontal_error=0.5, area_ratio=0.02)
        service._controller_action(FakeDetection(0.5), visible)
        now[0] += 0.1
        missing = MODULE.Observation(False)
        held = service._controller_action(None, missing)
        self.assertEqual(held.state, MODULE.ControlState.REACQUIRING)
        self.assertEqual((held.forward, held.turn), (0.0, 0.0))
        now[0] += 1.6
        searching = service._controller_action(None, missing)
        self.assertEqual(searching.state, MODULE.ControlState.SEARCHING)
        self.assertNotEqual(searching.turn, 0.0)

    def test_close_target_loss_after_approach_latches_arrival(self):
        now = [10.0]
        service = MODULE.AutonomyService(
            FakeGateway(),
            lambda _target, _confidence: FakeDetector(),
            clock=lambda: now[0],
        )
        visible = MODULE.Observation(True, horizontal_error=0.1, area_ratio=0.070)
        approach = service._controller_action(FakeDetection(0.1, 0.070), visible)
        self.assertEqual(approach.state, MODULE.ControlState.APPROACHING)
        service.last_action = approach.to_dict()

        now[0] += 0.1
        arrived = service._controller_action(None, MODULE.Observation(False))

        self.assertEqual(arrived.state, MODULE.ControlState.ARRIVED)
        self.assertTrue(service.controller.arrived)

    def test_close_target_loss_uses_latest_not_historical_geometry(self):
        now = [10.0]
        service = MODULE.AutonomyService(
            FakeGateway(),
            lambda _target, _confidence: FakeDetector(),
            clock=lambda: now[0],
        )
        close = MODULE.Observation(True, horizontal_error=0.1, area_ratio=0.07)
        service._controller_action(FakeDetection(0.1, 0.07), close)
        far = MODULE.Observation(True, horizontal_error=0.1, area_ratio=0.02)
        service.last_action = service._controller_action(
            FakeDetection(0.1, 0.02), far
        ).to_dict()
        now[0] += 0.1

        missing = service._controller_action(None, MODULE.Observation(False))

        self.assertEqual(missing.state, MODULE.ControlState.REACQUIRING)

    def test_close_loss_does_not_claim_arrival_when_target_was_off_centre(self):
        now = [10.0]
        service = MODULE.AutonomyService(
            FakeGateway(),
            lambda _target, _confidence: FakeDetector(),
            clock=lambda: now[0],
        )
        visible = MODULE.Observation(True, horizontal_error=0.7, area_ratio=0.07)
        service.last_action = service._controller_action(
            FakeDetection(0.7, 0.07), visible
        ).to_dict()
        now[0] += 0.1

        missing = service._controller_action(None, MODULE.Observation(False))

        self.assertEqual(missing.state, MODULE.ControlState.REACQUIRING)

    def test_bottom_edge_target_latches_arrival_before_loss(self):
        service = MODULE.AutonomyService(
            FakeGateway(), lambda _target, _confidence: FakeDetector()
        )
        detection = FakeDetection(0.1, 0.05, 0.93)
        observation = MODULE.Observation(
            True,
            horizontal_error=0.1,
            area_ratio=0.05,
            bottom_edge_ratio=0.93,
        )

        arrived = service._controller_action(detection, observation)

        self.assertEqual(arrived.state, MODULE.ControlState.ARRIVED)

    def test_disarm_during_inference_cannot_send_a_late_motion_command(self):
        detector = BlockingDetector()
        service, gateway = self.make_service(detector)
        service.arm()
        wait_for(detector.entered.is_set)
        service.disarm()
        detector.release.set()
        time.sleep(0.03)
        self.assertEqual(gateway.actions, [(0.0, 0.0)])

    def test_configuration_requires_disarm_and_reloads_target(self):
        service, _gateway = self.make_service(FakeDetector())
        service.arm()
        with self.assertRaises(RuntimeError):
            service.configure({"target": "bottle"})
        service.disarm()
        configured = service.configure({"target": "bottle", "max_forward": 0.5})
        self.assertEqual(configured["target"], "bottle")
        self.assertEqual(configured["controller_config"]["max_forward"], 0.5)

    def test_invalid_target_is_rejected(self):
        service, _gateway = self.make_service(FakeDetector())
        with self.assertRaises(ValueError):
            service.configure({"target": "mandarin"})

    def test_expired_mission_rejects_motion_and_fault_handler_stops(self):
        now = [10.0]
        gateway = FakeGateway()
        service = MODULE.AutonomyService(gateway, lambda *_: FakeDetector(),
                                        clock=lambda: now[0], mission_timeout_s=2)
        service._load_detector_if_needed()
        service.arm()
        now[0] = 12.0
        with self.assertRaisesRegex(TimeoutError, "mission exceeded") as caught:
            service._step()
        service._record_fault(caught.exception)
        self.assertEqual(gateway.actions, [(0.0, 0.0)])
        self.assertFalse(service.status()["armed"])

    def test_deadline_expiring_during_inference_cannot_send_late_motion(self):
        now = [10.0]
        class SlowDetector(FakeDetector):
            def detect(self, jpeg):
                now[0] = 13.0
                return super().detect(jpeg)
        gateway = FakeGateway()
        service = MODULE.AutonomyService(gateway, lambda *_: SlowDetector(FakeDetection()),
                                        clock=lambda: now[0], mission_timeout_s=2)
        service._load_detector_if_needed()
        service.arm()
        with self.assertRaisesRegex(TimeoutError, "mission exceeded"):
            service._step()
        self.assertEqual(gateway.actions, [])

    def test_rearming_starts_a_new_bounded_window(self):
        now = [10.0]
        service = MODULE.AutonomyService(FakeGateway(), lambda *_: FakeDetector(),
                                        clock=lambda: now[0], mission_timeout_s=2)
        service._load_detector_if_needed()
        service.arm()
        now[0] = 11.0
        self.assertEqual(service.status()["mission_remaining_s"], 1)
        service.disarm()
        self.assertIsNone(service.status()["mission_remaining_s"])
        now[0] = 14.0
        service.arm()
        self.assertEqual(service.status()["mission_remaining_s"], 2)

    def test_monitor_fault_ends_monitoring_instead_of_retrying_forever(self):
        service, gateway = self.make_service(FakeDetector(error=RuntimeError("camera lost")))
        service.start_monitor()
        wait_for(lambda: service.status()["state"] == "fault")
        self.assertFalse(service.status()["monitoring"])
        self.assertFalse(service.status()["perception_source"]["live"])
        self.assertEqual(gateway.actions[-1], (0.0, 0.0))

    def test_invalid_mission_timeout_is_rejected(self):
        for seconds in [0, 121, float("nan"), float("inf")]:
            with self.assertRaises(ValueError):
                MODULE.AutonomyService(FakeGateway(), lambda *_: FakeDetector(),
                                       mission_timeout_s=seconds)


if __name__ == "__main__":
    unittest.main()
