#!/usr/bin/env python3
"""Static integration checks for the B8 centralized control gate."""

import argparse
import re
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


REQUIRED_ENTITY_PATHS = {
    "/api/command/enable_all",
    "/api/command/disable_all",
    "/api/command/return_arm_zero",
    "/api/command/return_z_zero",
    "/api/command/set_zero",
    "/api/command/jog_axis",
    "/api/command/jog_axis_continuous",
    "/api/command/recovery_jog_axis",
    "/api/command/endpoint_jog",
    "/api/command/endpoint_target",
    "/api/command/targets",
    "/api/command/recover_arm_zero",
    "/api/acupoint_sequence/start",
    "/api/motion_test/sequence/start",
    "/api/mode/switch",
}


class IntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ROOT
        cls.web = (ROOT / "src/web/main_web.cpp").read_text(encoding="utf-8")
        cls.motor = (ROOT / "src/motor/main_motor.cpp").read_text(encoding="utf-8")
        cls.control = (ROOT / "src/control/main_control.cpp").read_text(encoding="utf-8")
        cls.gate = (ROOT / "src/common/control_safety_gate.cpp").read_text(encoding="utf-8")
        cls.defaults = (ROOT / "src/common/shared_memory_defaults.cpp").read_text(encoding="utf-8")

    def test_all_required_entity_paths_share_classifier(self):
        for path in REQUIRED_ENTITY_PATHS:
            self.assertIn(f'"{path}"', self.gate, path)
            self.assertIn(f'server.Post("{path}"', self.web, path)

    def test_every_api_post_is_classified_or_unknown_fail_closed(self):
        posts = set(re.findall(r'server\.Post\("([^"]+)"', self.web))
        classified = set(re.findall(r'"(/api/[^"]+)"', self.gate))
        self.assertTrue(posts <= classified, sorted(posts - classified))
        self.assertIn('req.path.rfind("/api/", 0)', self.web)
        self.assertIn("ControlActionKind::Unknown", self.gate)
        self.assertIn("unknown_control_action", self.gate)

    def test_web_uses_one_pre_request_gate(self):
        self.assertEqual(self.web.count("set_pre_request_handler"), 1)
        self.assertIn("classify_control_post(req.path)", self.web)
        self.assertIn("evaluate_control_safety(", self.web)
        self.assertIn("control_safety_snapshot(*state)", self.web)

    def test_motor_rechecks_before_consumers(self):
        helper = self.motor.index("evaluate_queued_entity_control")
        hardware_entry = self.motor.index("int run_hardware")
        initialize = self.motor.index("initialize_hardware(state, runtime)", hardware_entry)
        command_consumer = self.motor.index("if (state.command.command_seq != last_command_seq)")
        command_gate = self.motor.index("evaluate_queued_entity_control(state)", command_consumer)
        first_command = self.motor.index("enable_all(state, runtime)", command_consumer)
        target_consumer = self.motor.index("state.command.target_command_seq != last_target_seq", command_consumer)
        target_gate = self.motor.index("evaluate_queued_entity_control(state)", target_consumer)
        target_send = self.motor.index("send_targets(state, runtime)", target_consumer)
        self.assertLess(helper, command_consumer)
        # H1 is a lightweight status snapshot; hardware initialization is no
        # longer blocked by a complete H1 evidence package.
        self.assertNotIn("startup_gate", self.motor[hardware_entry:initialize])
        self.assertLess(command_gate, first_command)
        self.assertLess(target_gate, target_send)

    def test_endpoint_consumer_rechecks_before_target_write(self):
        consume = self.control.index("ep.valid == 1")
        gate = self.control.index("evaluate_endpoint_consumption(*state)", consume)
        target_write = self.control.index("apply_joints(*state", consume)
        self.assertLess(gate, target_write)

    def test_defaults_are_readonly_pass_and_motion_fail_closed(self):
        self.assertIn('"H1_BASIC_READONLY"', self.defaults)
        self.assertIn("execution_allowed = 0", self.defaults)
        self.assertIn("entity_action_authorized = 0", self.defaults)
        self.assertIn('"SIMULATION"', self.defaults)

    def test_simulation_declares_all_entity_outputs_false(self):
        route = self.web[self.web.index('server.Post("/api/motion_test/simulate"'):]
        route = route[: route.index('server.Post("/api/motion_test/point"')]
        for field in (
            '"execution_allowed\\\":false',
            '"entity_action_authorized\\\":false',
            '"motor_command_generated\\\":false',
            '"motor_target_generated\\\":false',
            '"serial_payload_generated\\\":false',
        ):
            self.assertIn(field, route)

    def test_new_gate_has_no_device_dependency(self):
        lowered = self.gate.lower()
        for forbidden in ("/dev/tty", "serial", "d405", "realsense", "mf9025"):
            self.assertNotIn(forbidden, lowered)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args, remaining = parser.parse_known_args()
    ROOT = args.root.resolve()
    unittest.main(argv=[__file__, *remaining])
