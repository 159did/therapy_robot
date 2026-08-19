#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "b5_h1_preflight.py"
spec = importlib.util.spec_from_file_location("b5_h1_preflight", MODULE)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class H1PreflightTests(unittest.TestCase):
    def test_preflight_is_read_only_and_permissions_are_false(self) -> None:
        result = module.run(Path(__file__).resolve().parents[1])
        self.assertTrue(result["read_only"])
        self.assertFalse(result["entity_serial_accessed"])
        self.assertFalse(result["entity_d405_accessed"])
        self.assertFalse(result["execution_allowed"])
        self.assertFalse(result["entity_action_authorized"])
        self.assertFalse(result["nano_deployment_authorized"])
        self.assertFalse(result["h1_window_authorized"])
