#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "github_private_preflight.py"
SPEC = importlib.util.spec_from_file_location("github_private_preflight_test", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class GitHubPrivatePreflightTests(unittest.TestCase):
    def test_current_repository_is_private_only_and_has_no_upload_blocker(self):
        report = MODULE.run(ROOT, allow_dirty=True)
        self.assertTrue(report["ready_for_private_push"])
        self.assertFalse(report["ready_for_public_push"])
        self.assertTrue(report["private_only_required"])
        self.assertEqual(report["push_scope"], "main_only")
        self.assertEqual(report["tracked_archives"], [])
        self.assertEqual(report["credential_named_files"], [])
        self.assertEqual(report["oversized_files"], [])
        self.assertGreater(report["sensitive_candidate_count"], 0)

    def test_credential_path_classifier(self):
        for path in ("id_ed25519", "keys/server.pem", "x/client.p12", ".netrc"):
            with self.subTest(path=path):
                self.assertTrue(MODULE.is_credential_path(path))
        for path in ("config/example.env", "docs/key-policy.md", "image.png"):
            with self.subTest(path=path):
                self.assertFalse(MODULE.is_credential_path(path))

    def test_publication_scan_includes_copied_vision_results(self):
        findings = MODULE.load_safety_scan(ROOT).run(ROOT)["findings"]
        self.assertIn(
            "docs/tasks/B5-VISION-PAPER-RESULTS/01_input_rgb.png",
            findings["captured_back_sample"],
        )


if __name__ == "__main__":
    unittest.main()
