#!/usr/bin/env python3
"""Dependency-light runner for Task 3D delayed-nowcast contract tests."""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "tests" / "test_task3a_v2_audit.py",
        root / "tests" / "test_task3b_v2a.py",
        root / "tests" / "test_task3c_prospective.py",
        root / "tests" / "test_task3d_delayed_nowcast.py",
    ]
    failures = []
    total = 0
    for path in paths:
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load test module: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        tests = [
            getattr(module, name)
            for name in dir(module)
            if name.startswith("test_") and callable(getattr(module, name))
        ]
        for test in tests:
            total += 1
            try:
                result = test()
                print(f"PASS {test.__name__}" if result is None else f"PASS {test.__name__}: {result}")
            except Exception as exc:  # pragma: no cover - runner reporting
                failures.append((test.__name__, exc))
                print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"Task 3A–3D contract tests: {total - len(failures)}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
