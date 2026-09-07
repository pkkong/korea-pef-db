#!/usr/bin/env python3
"""Discover function and unittest regressions, isolating each file in a process.

The default search covers scripts/tests and every services/**/tests directory.
Compatibility wrappers outside those directories are not duplicate test suites.
Individual test scripts can reuse run_module_tests instead of maintaining lists.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[1]


def collect_module_tests(module: ModuleType) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    for name, value in sorted(vars(module).items()):
        if getattr(value, "__module__", None) != module.__name__:
            continue
        if inspect.isclass(value) and issubclass(value, unittest.TestCase):
            suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(value))
        elif name.startswith("test_") and inspect.isfunction(value):
            suite.addTest(unittest.FunctionTestCase(value))
    return suite


def _run_module(module: ModuleType) -> unittest.TestResult:
    suite = collect_module_tests(module)
    if suite.countTestCases() == 0:
        raise ValueError(f"No tests discovered in {module.__file__}")
    return unittest.TextTestRunner(verbosity=1).run(suite)


def run_module_tests(module: ModuleType) -> int:
    """Run a legacy test script's complete local test namespace."""
    try:
        result = _run_module(module)
    except ValueError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


def discover_test_files(paths: list[Path] | None = None) -> list[Path]:
    roots = paths if paths is not None else [REPO_ROOT / "scripts" / "tests", REPO_ROOT / "services"]
    files: set[Path] = set()
    for root in roots:
        root = root.resolve()
        if not root.exists():
            raise ValueError(f"Test path does not exist: {root}")
        if root.is_file():
            files.add(root)
            continue
        for path in root.rglob("test_*.py"):
            if paths is not None or "tests" in path.relative_to(REPO_ROOT).parts:
                files.add(path)
    return sorted(files)


def _run_file(path: Path, result_file: Path) -> int:
    # A fresh process per file contains sys.path changes, import aliases and
    # mutable module caches used by the older script-based test suites.
    sys.path.insert(0, str(REPO_ROOT))
    name = "regression_" + hashlib.sha256(str(path).encode()).hexdigest()[:16]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load test module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    result = _run_module(module)
    result_file.write_text(
        json.dumps({
            "tests": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "skipped": len(result.skipped),
            "unexpected_successes": len(result.unexpectedSuccesses),
        }),
        encoding="utf-8",
    )
    return 0 if result.wasSuccessful() else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", type=Path, nargs="*", help="Optional test files or directories")
    parser.add_argument("--timeout", type=int, default=180, help="Maximum seconds per test file")
    parser.add_argument("--verbose", action="store_true", help="Show output from successful files too")
    parser.add_argument("--run-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--result-file", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.run_file:
        if not args.result_file:
            parser.error("--run-file requires --result-file")
        return _run_file(args.run_file.resolve(), args.result_file)
    try:
        files = discover_test_files(args.paths or None)
    except ValueError as exc:
        parser.error(str(exc))
    if not files:
        print("FAIL No regression test files discovered", file=sys.stderr)
        return 1
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0, "unexpected_successes": 0}
    failed_files = 0
    with tempfile.TemporaryDirectory(prefix="kpef-regression-results-") as temp_dir:
        for index, path in enumerate(files):
            result_file = Path(temp_dir) / f"{index}.json"
            try:
                result = subprocess.run(
                    [sys.executable, str(Path(__file__).resolve()), "--run-file", str(path),
                     "--result-file", str(result_file)],
                    cwd=REPO_ROOT,
                    text=True,
                    capture_output=True,
                    timeout=args.timeout,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                print(f"FAIL {path}: {exc}", flush=True)
                failed_files += 1
                continue
            counts = json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else {}
            for key in totals:
                totals[key] += counts.get(key, 0)
            successful = result.returncode == 0 and counts.get("tests", 0) > 0
            failed_files += not successful
            label = path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path
            print(f"{'PASS' if successful else 'FAIL'} {label} ({counts.get('tests', 0)} tests, "
                  f"{counts.get('skipped', 0)} skipped)", flush=True)
            if not successful or args.verbose:
                print(result.stdout + result.stderr, end="", flush=True)
    executed = totals["tests"] - totals["skipped"]
    print(f"Regression results: {totals['tests']} tests, {totals['failures']} failures, "
          f"{totals['errors']} errors, {totals['skipped']} skipped, "
          f"{totals['unexpected_successes']} unexpected successes; {failed_files}/{len(files)} files failed")
    return 0 if not failed_files and executed > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
