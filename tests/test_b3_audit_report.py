import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_b3_audit_report.py"
GENESIS = "sha256:" + "0" * 64


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


def event(sequence, event_type, previous, payload=None):
    value = {
        "sequence": sequence,
        "event_type": event_type,
        "occurred_at_ms": 1700000000000 + sequence,
        "source": "fixture",
        "evidence_kind": "offline_fixture",
        "payload": payload or {"result": "pass"},
        "previous_event_hash": previous,
    }
    value["event_hash"] = "sha256:" + hashlib.sha256(canonical(value)).hexdigest()
    return value


class AuditReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manifest = {
            "schema_version": "b3.audit-manifest.v1",
            "source_commit": "ad971a0efecc8169babea88c50d4f637ed9a34bb",
            "build_artifact_hashes": {"host_binary": "sha256:" + "1" * 64},
            "config_hashes": {"software": "sha256:" + "2" * 64},
            "input_hashes": {},
            "entity_access_declaration": {
                "nano_deployed": False,
                "entity_serial_accessed": False,
                "entity_d405_accessed": False,
                "motors_enabled": False,
                "motors_zeroed": False,
                "motors_moved": False,
            },
        }
        self.readiness = {
            "schema_version": "b3.v1",
            "ok": True,
            "motor_command_written": False,
            "execution_allowed": False,
            "entity_action_authorized": False,
            "nano_deployment_authorized": False,
            "authorization_scope": "software_precheck_only",
            "attestation_id": "attestation-fixture",
            "issued_at_ms": 1700000000000,
            "expires_at_ms": 1700000000300,
            "source_state": {"command_seq": 0, "target_command_seq": 0, "endpoint_target_seq": 0},
            "source_fingerprint": "fixture-source",
            "software_commit": self.manifest["source_commit"],
            "config_hashes": self.manifest["config_hashes"],
            "checks": [{"name": "static", "ok": True}],
            "blocking_reasons": [],
        }
        fixed = {
            "motor_command_written": False,
            "execution_allowed": False,
            "entity_action_authorized": False,
            "nano_deployment_authorized": False,
        }
        self.k0 = {
            "schema_version": "b3.k0-prepare-sim.v1",
            **fixed,
            "state_trace": [{"state": "safe"}],
            "operator_confirmation_points": [],
            "stop_reasons": ["simulation_complete"],
            "final_safe_state": True,
        }
        self.camera = {
            "schema_version": "b3.camera-extrinsics-candidate.v1",
            "candidate_id": "candidate-fixture",
            **fixed,
            "formal_use_allowed": False,
            "promotion_locked": True,
            "fit_input_hashes": {"fit": "sha256:" + "3" * 64},
            "validation_input_hashes": {"validation": "sha256:" + "4" * 64},
        }
        self.tests = {
            "schema_version": "b3.audit-test-results.v1",
            **fixed,
            "results": [{"name": "audit-unit", "ok": True}],
        }
        first = event(1, "source_snapshot", GENESIS)
        self.events = {"schema_version": "b3.audit-events.v1", "events": [first, event(2, "test_results_observed", first["event_hash"])]}
        input_values = (("readiness", self.readiness), ("k0", self.k0), ("camera", self.camera), ("test-results", self.tests), ("events", self.events))
        for name, value in input_values:
            (self.root / (name + ".json")).write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        self.manifest["input_hashes"] = {
            name: "sha256:" + hashlib.sha256((self.root / (name + ".json")).read_bytes()).hexdigest()
            for name, _ in input_values
        }
        (self.root / "manifest.json").write_text(json.dumps(self.manifest, sort_keys=True), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def run_generator(self, output, include_inputs=True):
        args = [sys.executable, str(SCRIPT), "--manifest", str(self.root / "manifest.json"), "--readiness", str(self.root / "readiness.json"), "--k0", str(self.root / "k0.json"), "--camera", str(self.root / "camera.json"), "--test-results", str(self.root / "test-results.json"), "--events", str(self.root / "events.json"), "--output", str(output)]
        if include_inputs:
            for name in self.manifest["input_hashes"]:
                args.extend(("--input-file", f"{name}={self.root / (name + '.json')}"))
        return subprocess.run(args, text=True, capture_output=True)

    def test_valid_inputs_are_deterministic(self):
        one = self.root / "one.json"
        two = self.root / "two.json"
        result_one = self.run_generator(one)
        result_two = self.run_generator(two)
        self.assertEqual(result_one.returncode, 0, result_one.stderr)
        self.assertEqual(result_two.returncode, 0, result_two.stderr)
        self.assertEqual(one.read_bytes(), two.read_bytes())
        report = json.loads(one.read_text(encoding="utf-8"))
        self.assertTrue(report["valid"])
        self.assertFalse(report["execution_allowed"])
        self.assertEqual(report["report_id"], "b3-audit-" + report["report_hash"][:16])

    def test_tampered_event_is_invalid_and_nonzero(self):
        data = json.loads((self.root / "events.json").read_text(encoding="utf-8"))
        data["events"][1]["payload"]["result"] = "tampered"
        (self.root / "events.json").write_text(json.dumps(data), encoding="utf-8")
        self.manifest["input_hashes"]["events"] = "sha256:" + hashlib.sha256((self.root / "events.json").read_bytes()).hexdigest()
        (self.root / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        output = self.root / "invalid.json"
        result = self.run_generator(output)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(json.loads(output.read_text(encoding="utf-8"))["valid"])

    def test_declared_input_requires_explicit_matching_file(self):
        manifest = self.manifest.copy()
        manifest["input_hashes"] = {"fixture": "sha256:" + "a" * 64}
        (self.root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        output = self.root / "invalid-input.json"
        result = self.run_generator(output, include_inputs=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing explicit input files", result.stderr)

    def test_empty_hash_collection_is_invalid(self):
        manifest = self.manifest.copy()
        manifest["input_hashes"] = {}
        (self.root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        output = self.root / "empty-hashes.json"
        result = self.run_generator(output, include_inputs=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hash collections must be non-empty", result.stderr)

    def test_entity_evidence_kind_is_rejected(self):
        data = json.loads((self.root / "events.json").read_text(encoding="utf-8"))
        data["events"][0]["evidence_kind"] = "entity"
        (self.root / "events.json").write_text(json.dumps(data), encoding="utf-8")
        self.manifest["input_hashes"]["events"] = "sha256:" + hashlib.sha256((self.root / "events.json").read_bytes()).hexdigest()
        (self.root / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        output = self.root / "invalid-entity.json"
        result = self.run_generator(output)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(json.loads(output.read_text(encoding="utf-8"))["valid"])


if __name__ == "__main__":
    unittest.main()
