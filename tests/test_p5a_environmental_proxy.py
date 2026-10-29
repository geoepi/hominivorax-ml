#!/usr/bin/env python3
"""Standard-library contract tests for the P5A proxy definitions."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.p5a_environmental_proxy.scripts.run_p5a_environmental_proxy import (
    ENV_COUNT,
    E2_MIN_SEASONAL_CYCLES,
    FEATURE_COUNT,
    ENVIRONMENTAL_FEATURES,
    add_weeks,
    build_proxy_environment,
    issue_timestamp,
    latest_available_week,
    proxy_applicability,
    seasonal_cycle_count,
)


class P5AContractTests(unittest.TestCase):
    def test_issue_time_and_week_boundary(self) -> None:
        self.assertEqual(add_weeks("2025-W52", 1), "2026-W01")
        self.assertEqual(latest_available_week("2026-W01"), "2025-W52")
        self.assertEqual(issue_timestamp("2026-W36"), "2026-09-07T00:00:00Z")

    def test_proxy_applicability_only_targets_environment(self) -> None:
        table = proxy_applicability()
        self.assertEqual(len(table), FEATURE_COUNT)
        self.assertEqual(int(table["proxy_applicable"].sum()), ENV_COUNT)
        self.assertEqual(set(table.loc[table["proxy_applicable"], "predictor"]), set(ENVIRONMENTAL_FEATURES))
        self.assertFalse(table.loc[table["predictor"] == "week_sin", "proxy_applicable"].iloc[0])

    def test_e0_and_e1_use_only_prior_fixed_windows(self) -> None:
        labels = ["2026-W01", "2026-W02", "2026-W03", "2026-W04", "2026-W05"]
        dynamic = np.arange(len(labels) * 2 * ENV_COUNT, dtype=float).reshape(len(labels), 2, ENV_COUNT)
        e0, e0_meta = build_proxy_environment(dynamic, labels, "2026-W04", "E0_LAST_AVAILABLE")
        e1, e1_meta = build_proxy_environment(dynamic, labels, "2026-W04", "E1_TRAILING3_MEAN")
        np.testing.assert_array_equal(e0[0], dynamic[2])
        np.testing.assert_allclose(e1[0], dynamic[0:3].mean(axis=0))
        self.assertEqual(e0_meta["latest_available_week"], "2026-W03")
        self.assertEqual(e1_meta["window"], "2026-W01;2026-W02;2026-W03")

    def test_e2_requires_two_prior_seasonal_cycles(self) -> None:
        labels = ["2025-W01", "2026-W01", "2026-W02"]
        self.assertEqual(seasonal_cycle_count(labels, "2026-W02", "2026-W01"), 0)
        self.assertEqual(E2_MIN_SEASONAL_CYCLES, 2)


if __name__ == "__main__":
    unittest.main()
