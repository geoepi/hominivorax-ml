"""Small executable test for the development-only final-test guard."""

from __future__ import annotations


def assert_development_guard(weeks: list[str], evaluation_mode: str = "development") -> None:
    final_start = weeks.index("2026-W04")
    if evaluation_mode != "final":
        raise RuntimeError("development mode prohibits final-test predictive metrics")
    if final_start < 0:  # pragma: no cover
        raise AssertionError("final-test start week missing")


if __name__ == "__main__":
    try:
        assert_development_guard(["2026-W04"], "development")
    except RuntimeError:
        print("final-test guard: PASS")
    else:  # pragma: no cover
        raise SystemExit("guard failed")
