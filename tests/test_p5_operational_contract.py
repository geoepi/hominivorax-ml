"""Standard-library P5 contract tests; no pytest dependency required."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "analysis" / "p5_operational_contract" / "scripts"))
from p5_contract import (  # noqa: E402
    P5ContractError,
    freshness_status,
    issue_timestamp,
    target_week,
    validate_target_rows,
)


class P5ContractTests(unittest.TestCase):
    def test_iso_week_boundary_and_issue_timestamp(self) -> None:
        self.assertEqual(target_week("2020-W53", 1), "2021-W01")
        self.assertEqual(target_week("2021-W01", 1), "2021-W02")
        self.assertEqual(issue_timestamp("2026-W16").isoformat(), "2026-04-20T00:00:00+00:00")

    def test_target_contract_rejects_future_or_duplicate_rows(self) -> None:
        with self.assertRaises(P5ContractError) as duplicate:
            validate_target_rows("2026-W40", [{"target_week": "2026-W41", "horizon": 1}, {"target_week": "2026-W41", "horizon": 1}])
        self.assertEqual(duplicate.exception.code, "DUPLICATE_TARGET_WEEK")

    def test_freshness_states_are_deterministic(self) -> None:
        self.assertEqual(freshness_status("2026-10-01T00:00:00Z", "2026-10-05T00:00:00Z", "AVAILABLE_AS_OF_ISSUE"), "CURRENT")
        self.assertEqual(freshness_status("2026-10-06T00:00:00Z", "2026-10-05T00:00:00Z", "AVAILABLE_AS_OF_ISSUE"), "FUTURE_DATED")
        self.assertEqual(freshness_status("2026-09-01T00:00:00Z", "2026-10-05T00:00:00Z", "RETROSPECTIVE_ONLY"), "STALE_BLOCKING")


if __name__ == "__main__":
    unittest.main()
