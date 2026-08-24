import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("capture_d405", ROOT / "scripts" / "capture_d405.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CaptureD405Tests(unittest.TestCase):
    def test_default_is_non_live(self):
        self.assertEqual(MODULE.capture(MODULE.argparse.Namespace(live=False)), 0)

    def test_metadata_is_locked_for_robot(self):
        value = MODULE.bundle_metadata(Path("/tmp/bundle"), "serial", 640, 480, 30)
        self.assertTrue(value["hardware_access"]["d405_accessed"])
        self.assertFalse(value["hardware_access"]["serial_accessed"])
        self.assertFalse(value["robot_control"]["execution_allowed"])


if __name__ == "__main__":
    unittest.main()
