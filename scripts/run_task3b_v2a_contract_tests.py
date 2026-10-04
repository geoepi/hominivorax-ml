#!/usr/bin/env python3
"""Run Task 3B contract tests without requiring pytest."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    path = repo / "tests" / "test_task3b_v2a.py"
    spec = importlib.util.spec_from_file_location("test_task3b_v2a", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    names = [name for name in dir(module) if name.startswith("test_")]
    for name in names:
        getattr(module, name)()
    print({"status": "PASS", "tests": names})


if __name__ == "__main__":
    main()
