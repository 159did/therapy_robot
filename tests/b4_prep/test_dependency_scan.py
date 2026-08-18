import ast
import re
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
LOCAL_SCRIPTS = HERE
WORKTREE_SCRIPTS = HERE.parents[1] / "scripts" / "b4_prep"
SCRIPTS = WORKTREE_SCRIPTS if WORKTREE_SCRIPTS.exists() else LOCAL_SCRIPTS


class DependencyScanTests(unittest.TestCase):
    def test_production_scripts_have_no_control_dependencies_or_endpoints(self):
        files = sorted(path for path in SCRIPTS.glob("*.py") if "test_" not in path.name)
        self.assertGreaterEqual(len(files), 3)
        forbidden_text = {
            "/dev/tty": "entity serial device",
            "serial.Serial": "serial runtime",
            "pyserial": "serial dependency",
            "subprocess.Popen": "process launch",
            "subprocess.run": "process execution",
            "requests.post": "control HTTP POST",
            "/api/command/": "control endpoint",
            "--execute": "execution CLI",
            "deploy-jetson": "Nano deployment",
            "camera_to_base.json": "formal calibration file",
        }
        for path in files:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = {alias.name for alias in node.names}
                    self.assertNotIn("serial", names, path)
                    self.assertNotIn("shared_memory", names, path)
                if isinstance(node, ast.ImportFrom):
                    self.assertNotEqual(node.module, "serial", path)
                    self.assertNotEqual(node.module, "multiprocessing.shared_memory", path)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    qualified = f"{ast.unparse(node.func.value)}.{node.func.attr}"
                    self.assertNotIn(qualified, {"serial.Serial", "subprocess.Popen", "subprocess.run", "requests.post"}, path)
            for token, description in forbidden_text.items():
                self.assertNotIn(token, source, f"{description}: {path}")

            # Validation-only forbidden-key names are acceptable; executable
            # control targets are not.
            self.assertIsNone(re.search(r"\b(?:motor_target|joint_target|command_target)\s*=", source))

    def test_scripts_are_ascii_and_parseable(self):
        for path in sorted(path for path in SCRIPTS.glob("*.py") if "test_" not in path.name):
            source = path.read_text(encoding="utf-8")
            source.encode("ascii")
            ast.parse(source, filename=str(path))


if __name__ == "__main__":
    unittest.main()
