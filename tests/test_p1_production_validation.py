"""Focused contract tests for exact frozen-artifact P1 validation."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).parents[1] / "analysis" / "p1_production_validation" / "scripts" / "run_p1_validation.py"
SPEC = importlib.util.spec_from_file_location("run_p1_validation", SCRIPT)
assert SPEC and SPEC.loader
P1_IMPORT_ERROR = None
try:
    p1 = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(p1)
except ModuleNotFoundError as exc:
    # The repository's minimal Windows runtime does not carry the Atlas
    # scientific stack.  Atlas execution is the authoritative runner for P1;
    # keep the contract tests importable in the minimal local environment.
    p1 = None
    P1_IMPORT_ERROR = str(exc)


@unittest.skipIf(p1 is None, f"Atlas scientific runtime unavailable locally: {P1_IMPORT_ERROR}")
class P1ValidationTests(unittest.TestCase):
    def test_frozen_schema_and_decision_rules_are_explicit(self) -> None:
        self.assertEqual(p1.EXPECTED_MODEL_ID, "STRUCTURED_A3")
        self.assertEqual(len(p1.EXPECTED_FEATURES), 34)
        self.assertIn("temporal", p1.DECISION_RULES)
        self.assertIn("spatiotemporal", p1.DECISION_RULES)
        self.assertIn("two-week", p1.DECISION_RULES["uncertainty"])

    def test_exact_scorer_is_deterministic_and_uses_frozen_constants(self) -> None:
        model = {
            "model": "STRUCTURED_A3",
            "theta": 0.7018903965556372,
            "preprocessing": {
                "training_mean": [0.0] * 34,
                "training_sd": [1.0] * 34,
            },
            "occurrence_coefficients": [0.0] * 35,
            "count_coefficients": [0.0] * 35,
        }
        matrix = np.zeros((3, 34), dtype=float)
        first = p1.score_frozen_model(model, matrix)
        second = p1.score_frozen_model(model, matrix)
        for left, right in zip(first, second):
            np.testing.assert_array_equal(left, right)
        self.assertTrue(np.allclose(first[0], 0.5))

    def test_frontier_categories_use_prior_history_not_random_rows(self) -> None:
        scored = pd.DataFrame(
            {
                "week": ["2026-W30"] * 4,
                "model_node_id": [0, 1, 2, 3],
                "observed_count": [2, 0, 1, 0],
                "p_occurrence": [0.8, 0.2, 0.7, 0.1],
                "conditional_count_mean": [2.0] * 4,
                "underlying_mu": [1.0] * 4,
                "expected_count": [1.6, 0.4, 1.4, 0.2],
            }
        )
        front = pd.DataFrame(
            {
                "week": ["2026-W30"] * 4,
                "model_node_id": [0, 1, 2, 3],
                "any_prior_positive_available": [1, 1, 0, 0],
                "prev4_positive_available": [1, 1, 0, 0],
                "detection_within_50km_ever_available": [1, 1, 0, 0],
            }
        )
        result = p1.make_frontier_frame(scored, front)
        self.assertEqual(result.loc[0, "frontier_category"], "established_core")
        self.assertEqual(result.loc[1, "frontier_category"], "previously_occupied")
        self.assertEqual(result.loc[2, "frontier_category"], "newly_detected_frontier")
        self.assertEqual(result.loc[3, "frontier_category"], "previously_unoccupied")

    def test_bootstrap_contract_uses_grouped_regimes(self) -> None:
        rows = []
        for week_index in range(10):
            for node in range(20):
                rows.append(
                    {
                        "week": f"2026-W{week_index + 30:02d}",
                        "model_node_id": node,
                        "row": node,
                        "column": node,
                        "observed_count": int((week_index + node) % 3 == 0),
                        "p_occurrence": 0.1 + 0.01 * ((week_index + node) % 10),
                        "conditional_count_mean": 1.5,
                        "underlying_mu": 1.0,
                        "expected_count": 0.15,
                    }
                )
        frame = pd.DataFrame(rows)
        model = {
            "theta": 0.7018903965556372,
            "fit_info": {"training_positive_rows": 10, "training_rows": 100},
        }
        result = p1.block_bootstrap(frame, model, "temporal", 99, 20261029)
        self.assertTrue(result)
        self.assertTrue(all(row["resampling_unit"] == "ordered two-week blocks" for row in result))
        self.assertTrue(all(row["bootstrap_replicates"] > 0 for row in result))


if __name__ == "__main__":
    unittest.main()

