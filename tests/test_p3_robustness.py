"""Focused contracts for the P3 bounded robustness workflow."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).parents[1] / "analysis" / "p3_robustness" / "scripts" / "run_p3_robustness.py"
SPEC = importlib.util.spec_from_file_location("run_p3_robustness", SCRIPT)
assert SPEC and SPEC.loader
P3_IMPORT_ERROR = None
try:
    p3 = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(p3)
except ModuleNotFoundError as exc:
    p3 = None
    P3_IMPORT_ERROR = str(exc)


def synthetic_counts() -> tuple[np.ndarray, pd.DataFrame]:
    counts = np.zeros((5, 4), dtype=np.int64)
    counts[1, 0] = 1
    counts[2, 3] = 2
    nodes = pd.DataFrame({
        "model_node_id": np.arange(4),
        "row": [0, 0, 4, 8],
        "column": [0, 1, 4, 8],
        "lon": [-110.0, -109.75, -100.0, -90.0],
        "lat": [10.0, 21.0, 31.0, 35.0],
        "country_or_domain_region": ["Mexico", "Mexico", "U.S.-to-40N", "U.S.-to-40N"],
    })
    return counts, nodes


@unittest.skipIf(p3 is None, f"Atlas scientific runtime unavailable locally: {P3_IMPORT_ERROR}")
class P3ContractTests(unittest.TestCase):
    def test_frozen_identity_and_prespecified_definitions(self) -> None:
        self.assertEqual(p3.MODEL_ID, "STRUCTURED_A3")
        self.assertEqual(p3.P0_MODEL_SHA256, "8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e")
        self.assertEqual(p3.FRONTIER_DEFINITIONS, ["F0_reference", "F1_recent_8_week_occupancy", "F2_distance_to_prior_detection"])
        self.assertEqual(p3.COUNT_STRATA, ["low_1_2", "moderate_3_5", "high_6_10", "extreme_11_plus"])

    def test_frontier_classes_ignore_future_counts(self) -> None:
        counts, nodes = synthetic_counts()
        before = p3.frontier_labels(counts, 1, nodes)
        mutated = counts.copy()
        mutated[2:, 2:] = 99
        after = p3.frontier_labels(mutated, 1, nodes)
        for definition in p3.FRONTIER_DEFINITIONS:
            self.assertTrue(np.array_equal(before[definition], after[definition]))

    def test_distance_frontier_is_reproducible(self) -> None:
        counts, nodes = synthetic_counts()
        first = p3.frontier_labels(counts, 2, nodes)["F2_distance_to_prior_detection"]
        second = p3.frontier_labels(counts, 2, nodes)["F2_distance_to_prior_detection"]
        self.assertTrue(np.array_equal(first, second))
        self.assertIn("near_established", set(first))

    def test_count_strata_are_fixed(self) -> None:
        self.assertEqual([p3.count_stratum(x) for x in [1, 2, 3, 5, 6, 10, 11, 30]], [
            "low_1_2", "low_1_2", "moderate_3_5", "moderate_3_5",
            "high_6_10", "high_6_10", "extreme_11_plus", "extreme_11_plus",
        ])

    def test_partition_labels_are_not_performance_selected(self) -> None:
        frame = pd.DataFrame({
            "lat": [10.0, 25.0, 35.0],
            "lon": [-110.0, -100.0, -90.0],
            "country_or_domain_region": ["Mexico", "Mexico", "U.S.-to-40N"],
            "target_week": ["2026-W17", "2026-W21", "2026-W37"],
        })
        self.assertEqual(list(p3.spatial_label(frame, "S1_latitude_macroregion")), ["south_of_20N", "20_to_30N", "30_to_40N"])
        self.assertEqual(list(p3.spatial_label(frame, "S2_longitude_macroregion")), ["west_of_105W", "105W_to_95W", "east_of_95W"])
        self.assertEqual(list(p3.temporal_label(frame, "T1_fixed_four_week_block")), ["block_1", "block_2", "block_6"])

    def test_feature_groups_are_deterministic(self) -> None:
        self.assertEqual(p3.feature_group("intercept"), "intercept")
        self.assertEqual(p3.feature_group(p3.FEATURE_ORDER[0]), "dynamic_environment")
        self.assertEqual(p3.feature_group(p3.FEATURE_ORDER[24]), "detection_history")
        self.assertEqual(p3.feature_group(p3.FEATURE_ORDER[-1]), "augmentation_static")


if __name__ == "__main__":
    unittest.main()
