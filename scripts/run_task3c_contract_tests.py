#!/usr/bin/env python3
"""Dependency-light runner for the Task 3C contract tests."""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path


def main() -> int:
    path = Path(__file__).resolve().parents[1] / "tests" / "test_task3c_prospective.py"
    spec = importlib.util.spec_from_file_location("test_task3c_prospective", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load test module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tests = [getattr(module, name) for name in dir(module) if name.startswith("test_") and callable(getattr(module, name))]
    failures = []
    for test in tests:
        try:
            result = test()
            print(f"PASS {test.__name__}" if result is None else f"PASS {test.__name__}: {result}")
        except Exception as exc:  # pragma: no cover - runner reporting
            failures.append((test.__name__, exc))
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"Task 3C contract tests: {len(tests) - len(failures)}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
