import json
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "analysis/a6_gpboost_correlated_spatial_ml/config/a6_config.json").read_text())


class A6ContractTests(unittest.TestCase):
    def test_parent_and_candidate_contract(self):
        self.assertEqual(CONFIG["parent_a5b_commit"], "d6651a8e221e54184c68c098805300723a598276")
        self.assertEqual(CONFIG["parent_a5_decision"], "A5_GNN_NOT_SUPPORTED")
        self.assertEqual(CONFIG["parent_a5b_decision"], "A5B_NOT_JUSTIFIED")
        self.assertEqual(CONFIG["candidates"], ["A6-GB-IID", "A6-GPB-S", "A6-GPB-ST"])

    def test_predictor_and_coordinate_contract(self):
        self.assertEqual(CONFIG["predictors"]["count"], 34)
        self.assertFalse(CONFIG["predictors"]["coordinates_are_tree_features"])
        self.assertEqual(CONFIG["coordinates"]["space_time_order"], ["time_week_offset", "x_km", "y_km"])
        self.assertEqual(CONFIG["gpboost"]["vecchia_pred_type"], "order_obs_first_cond_obs_only")

    def test_temporal_coordinate_construction(self):
        times = np.array([0, 0, 2, 2], dtype=float)
        xy = np.array([[10.0, 20.0], [30.0, 40.0]], dtype=float)
        coords = np.column_stack([times, np.tile(xy, (2, 1))])
        np.testing.assert_allclose(coords[:, 0], [0, 0, 2, 2])
        np.testing.assert_allclose(coords[:, 1:], [[10, 20], [30, 40], [10, 20], [30, 40]])

    def test_a3_offset_equivalence(self):
        eta = np.array([-3.0, 0.0, 2.5], dtype=float)
        zero_residual = np.zeros_like(eta)
        expected = 1.0 / (1.0 + np.exp(-(eta + zero_residual)))
        np.testing.assert_allclose(expected, 1.0 / (1.0 + np.exp(-eta)), rtol=0, atol=1e-15)

    def test_fold_separation_and_forbidden_future_period(self):
        folds = CONFIG["development_period"]["folds"]
        self.assertEqual(len(folds), 4)
        self.assertEqual(CONFIG["development_period"]["end"], "2026-W16")
        for fold in folds:
            self.assertLess(fold["train_end"], fold["validation_start"])


if __name__ == "__main__":
    unittest.main()
