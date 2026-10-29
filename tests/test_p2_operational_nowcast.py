"""Focused contracts for the P2 operational rolling-origin workflow."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).parents[1] / "analysis" / "p2_operational_nowcast" / "scripts" / "run_p2_operational_nowcast.py"
SPEC = importlib.util.spec_from_file_location("run_p2_operational_nowcast", SCRIPT)
assert SPEC and SPEC.loader
P2_IMPORT_ERROR = None
try:
    p2 = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(p2)
except ModuleNotFoundError as exc:
    p2 = None
    P2_IMPORT_ERROR = str(exc)


def synthetic_predictions() -> pd.DataFrame:
    rows = []
    for origin_index, origin in enumerate(["2026-W16", "2026-W17"]):
        for horizon in [1, 2, 3]:
            target = f"2026-W{17 + origin_index + horizon - 1:02d}"
            for node in range(6):
                observed = int((node + horizon + origin_index) % 4 == 0)
                rows.append(
                    {
                        "origin_week": origin,
                        "target_week": target,
                        "horizon": horizon,
                        "model_node_id": node,
                        "row": node,
                        "column": node,
                        "lon": float(node),
                        "lat": float(node),
                        "country_or_domain_region": "Mexico" if node < 4 else "U.S.-to-40N",
                        "observed_count": observed * (node + 1),
                        "observed_positive": observed,
                        "p_occurrence": 0.1 + 0.1 * observed + 0.01 * node,
                        "conditional_count_mean": 1.5 + 0.2 * node,
                        "underlying_mu": 1.0 + 0.1 * node,
                        "expected_count": (0.1 + 0.1 * observed + 0.01 * node) * (1.5 + 0.2 * node),
                        "persistence_probability": float(node % 2 == 0),
                        "historical_prevalence_probability": 0.2,
                        "historical_reference_source": "historical_iso_week_prevalence",
                        "previously_occupied": bool(node % 2 == 0),
                        "prediction_frontier_class": "previously_occupied" if node % 2 == 0 else "previously_unoccupied",
                        "outcome_frontier_label": "established_core" if observed and node % 2 == 0 else "newly_detected_frontier" if observed else "not_positive",
                    }
                )
    return pd.DataFrame(rows)


@unittest.skipIf(p2 is None, f"Atlas scientific runtime unavailable locally: {P2_IMPORT_ERROR}")
class P2ContractTests(unittest.TestCase):
    def test_frozen_procedure_identity(self) -> None:
        self.assertEqual(p2.MODEL_ID, "STRUCTURED_A3")
        self.assertEqual(p2.FEATURE_COUNT, 34)
        self.assertEqual(p2.PENALTY, 0.01)
        self.assertEqual(p2.FIXED_THETA, 0.7018903965556372)
        self.assertEqual(p2.MAX_HORIZON, 3)
        self.assertEqual(p2.BOOTSTRAP_REPLICATES, 399)

    def test_historical_reference_uses_only_training_rows(self) -> None:
        labels = ["2025-W01", "2025-W02", "2026-W01", "2026-W02"]
        counts = np.asarray([[1, 0], [0, 0], [9, 9], [9, 9]], dtype=np.int64)
        before = p2.historical_prevalence(counts, labels, 1, "2026-W01")
        counts[2:, :] = 0
        after = p2.historical_prevalence(counts, labels, 1, "2026-W01")
        self.assertEqual(before, after)
        self.assertEqual(before[1], "historical_iso_week_prevalence")

    def test_calibration_bins_are_fixed_and_horizon_specific(self) -> None:
        frame = synthetic_predictions()
        rows = p2.calibration_bins(frame, "2")
        self.assertEqual(len(rows), 10)
        self.assertTrue(all(row["deterministic_rule"].startswith("10 fixed") for row in rows))
        self.assertEqual(sum(row["n"] for row in rows), int((frame["horizon"] == 2).sum()))

    def test_frontier_classes_are_prediction_time_strata(self) -> None:
        frame = synthetic_predictions()
        self.assertTrue(set(frame["prediction_frontier_class"]) == {"previously_occupied", "previously_unoccupied"})
        self.assertTrue(set(frame.loc[frame["outcome_frontier_label"] == "newly_detected_frontier", "prediction_frontier_class"]) == {"previously_unoccupied"})

    def test_bootstrap_samples_target_week_blocks(self) -> None:
        frame = synthetic_predictions()
        indices = p2.bootstrap_indices(frame, np.random.default_rng(20261029))
        sampled_weeks = set(frame.iloc[indices]["target_week"])
        self.assertTrue(sampled_weeks.issubset(set(frame["target_week"])))
        for week in sampled_weeks:
            self.assertEqual(int((frame.iloc[indices]["target_week"] == week).sum()) % 6, 0)

    def test_reference_comparison_has_only_two_references(self) -> None:
        result = p2.reference_metrics(synthetic_predictions())
        self.assertEqual(set(result["reference"]), {"persistence", "historical_prevalence"})
        self.assertTrue((result["coverage"] == 1.0).all())


if __name__ == "__main__":
    unittest.main()
