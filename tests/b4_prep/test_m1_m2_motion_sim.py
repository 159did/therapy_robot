#!/usr/bin/env python3
"""B4-PREP-C pure-software M1/M2 route simulation tests."""

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "b4_prep" / "m1_m2_motion_sim.py"
FIXTURE = ROOT / "tests" / "b4_prep" / "fixtures" / "m1_m2_motion" / "nominal.json"
SPEC = importlib.util.spec_from_file_location("m1_m2_motion_sim", SCRIPT)
SIM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIM)


class MotionPreparationSimulationTest(unittest.TestCase):
    def base(self):
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    def signed(self, mutator=None):
        value = self.base()
        if mutator is not None:
            mutator(value)
        value["payload_sha256"] = SIM.payload_sha256(value)
        return value

    def run_document(self, root, document):
        source = root / "input.json"; output = root / "result.json"
        source.write_text(json.dumps(document, allow_nan=True), encoding="utf-8")
        result = subprocess.run([sys.executable, str(SCRIPT), str(source), "--out", str(output)], cwd=ROOT, text=True, capture_output=True)
        return result, json.loads(output.read_text(encoding="utf-8"))

    def test_nominal_left_right_route_finishes_stowed_and_locked(self):
        with tempfile.TemporaryDirectory(prefix="b4c-nominal-") as directory:
            result, report = self.run_document(Path(directory), self.signed())
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue(report["simulation_valid"])
            self.assertEqual(report["schema_version"], "b4.m1-m2-sim.v1")
            self.assertEqual(report["metrics"]["action_count"], 10)
            self.assertEqual(report["final_state"], {"height_norm": 0.0, "lateral_norm": 0.0, "phase": "STOWED"})
            self.assertFalse(report["execution_allowed"]); self.assertFalse(report["entity_action_authorized"]); self.assertFalse(report["nano_deployment_authorized"])
            self.assertTrue(report["promotion_locked"]); self.assertFalse(report["formal_use_allowed"])
            self.assertFalse(report["recovery_allowed"]); self.assertTrue(report["resume_requires_new_authorization"])

    def test_emergency_watchdog_and_feedback_loss_stop_safely(self):
        for scenario in ("emergency_stop", "watchdog_timeout", "feedback_loss"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory(prefix="b4c-fault-") as directory:
                document = self.signed(lambda value: value.__setitem__("scenario", scenario))
                result, report = self.run_document(Path(directory), document)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertEqual(report["final_state"]["phase"], "STOPPED")
                self.assertEqual([item["event"] for item in report["events"]], ["stop_requested", "stopping", "stopped"])
                self.assertTrue(next(item for item in report["checks"] if item["id"] == "fault_safe_stop")["value"])

    def test_threshold_route_and_stop_distance_fail_closed(self):
        mutations = [
            lambda value: value["segments"][0]["actions"][0].__setitem__("speed_norm_s", 0.05),
            lambda value: value["segments"][0]["actions"][0].__setitem__("distance_norm", 0.01),
            lambda value: value["segments"][0]["actions"].reverse(),
            lambda value: value.__setitem__("segments", value["segments"][:1]),
            lambda value: value["segments"][0]["actions"][0].__setitem__("speed_norm_s", 1.0),
        ]
        for index, mutator in enumerate(mutations):
            with self.subTest(index=index), tempfile.TemporaryDirectory(prefix="b4c-invalid-") as directory:
                result, report = self.run_document(Path(directory), self.signed(mutator))
                self.assertEqual(result.returncode, 2); self.assertFalse(report["simulation_valid"]); self.assertTrue(report["blocking_reasons"])
                self.assertFalse(report["execution_allowed"]); self.assertFalse(report["entity_action_authorized"])

    def test_hash_nan_unknown_and_unit_tampering_fail_closed(self):
        documents = []
        tampered = self.signed(); tampered["scenario"] = "changed-without-resigning"; documents.append(tampered)
        documents.append(self.signed(lambda value: value["config"].__setitem__("min_speed_norm_s", float("nan"))))
        documents.append(self.signed(lambda value: value.__setitem__("unknown", True)))
        documents.append(self.signed(lambda value: value["units"].__setitem__("position", "millimeters")))
        for index, document in enumerate(documents):
            with self.subTest(index=index), tempfile.TemporaryDirectory(prefix="b4c-tamper-") as directory:
                result, report = self.run_document(Path(directory), document)
                self.assertEqual(result.returncode, 2); self.assertFalse(report["simulation_valid"])

    def test_simulation_id_is_deterministic_and_input_sensitive(self):
        with tempfile.TemporaryDirectory(prefix="b4c-repeat-") as directory:
            root = Path(directory); first_result, first = self.run_document(root, self.signed()); second_result, second = self.run_document(root, self.signed())
            self.assertEqual(first_result.returncode, second_result.returncode); self.assertEqual(first["simulation_id"], second["simulation_id"])
            changed_result, changed = self.run_document(root, self.signed(lambda value: value["segments"][0]["actions"][1].__setitem__("distance_norm", 0.21)))
            self.assertEqual(changed_result.returncode, 0); self.assertNotEqual(first["simulation_id"], changed["simulation_id"])

    def test_source_has_no_runtime_or_hardware_imports(self):
        text = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("import serial", "import subprocess", "import socket", "shared_memory", "/dev/tty", "run-jetson", "camera_to_base.json"):
            self.assertNotIn(forbidden, text)
        schema = json.loads((ROOT / "scripts" / "b4_prep" / "m1_m2_motion.schema.json").read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
