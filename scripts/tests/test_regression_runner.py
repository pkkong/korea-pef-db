"""The runner must include unlisted tests and reject an empty suite."""
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.run_regression_tests import collect_module_tests, discover_test_files, run_module_tests


class RegressionRunnerTests(unittest.TestCase):
    def test_collects_both_function_and_unittest_even_without_a_main_list(self):
        module = types.ModuleType("sample_tests")
        exec("import unittest\ndef test_function(): pass\nclass Tests(unittest.TestCase):\n def test_method(self): pass", module.__dict__)
        self.assertEqual(collect_module_tests(module).countTestCases(), 2)

    def test_empty_suite_fails_instead_of_passing(self):
        module = types.ModuleType("empty")
        module.__file__ = "empty.py"
        self.assertEqual(run_module_tests(module), 1)

    def test_only_test_files_are_discovered(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "test_example.py").touch()
            (root / "fixture.py").touch()
            self.assertEqual(discover_test_files([root]), [(root / "test_example.py").resolve()])
