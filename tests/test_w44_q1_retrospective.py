"""Focused leakage and environmental-proxy contracts for W44 Q1."""

from __future__ import annotations

import datetime as dt
import unittest

import numpy as np
import pandas as pd

from analysis.structured_a3_data_refresh_2026w44.qualification_execution import run_w44_q1_retrospective as q1
from analysis.structured_a3_data_refresh_2026w44.qualification_execution import record_w44_q1_resources as resources


def week_labels() -> list[str]:
    start = dt.date.fromisocalendar(2025, 1, 1)
    labels = []
    for index in range(96):
        iso = (start + dt.timedelta(weeks=index)).isocalendar()
        labels.append(f"{iso.year}-W{iso.week:02d}")
    return labels


class W44Q1Contracts(unittest.TestCase):
    def test_detection_history_is_held_at_issue_time_through_all_horizons(self) -> None:
        features = np.arange(6 * 3 * q1.p2.FEATURE_COUNT, dtype=float).reshape(6, 3, q1.p2.FEATURE_COUNT)
        target_indices = [3, 4, 5]
        held = q1.make_origin_target_features(features, target_indices, origin_index=2)
        np.testing.assert_array_equal(
            held[:, :, q1.HISTORY_INDICES],
            np.broadcast_to(features[3][:, q1.HISTORY_INDICES], (3, 3, len(q1.HISTORY_INDICES))),
        )
        non_history = np.setdiff1d(np.arange(q1.p2.FEATURE_COUNT), q1.HISTORY_INDICES)
        np.testing.assert_array_equal(held[:, :, non_history], features[target_indices][:, :, non_history])

    def test_e0_and_e1_use_only_the_approved_prior_environmental_weeks(self) -> None:
        labels = [f"2026-W{week:02d}" for week in range(1, 9)]
        dynamic = np.arange(8 * 3 * len(q1.ENVIRONMENTAL_INDICES), dtype=float).reshape(8, 3, -1)
        features = np.zeros((8, 3, q1.p2.FEATURE_COUNT), dtype=float)
        for proxy, expected in [
            ("E0_LAST_AVAILABLE", np.broadcast_to(dynamic[2][None, :, :], (3, 3, 12))),
            ("E1_TRAILING3_MEAN", np.broadcast_to(dynamic[0:3].mean(axis=0)[None, :, :], (3, 3, 12))),
        ]:
            actual = q1.make_proxy_target_features(features, dynamic, labels, "2026-W04", 3, proxy)
            np.testing.assert_array_equal(actual[:, :, q1.ENVIRONMENTAL_INDICES], expected)
            np.testing.assert_array_equal(actual[:, :, q1.HISTORY_INDICES], np.broadcast_to(features[4][:, q1.HISTORY_INDICES], (3, 3, len(q1.HISTORY_INDICES))))

    def test_authoritative_origin_table_maps_all_three_horizons(self) -> None:
        labels = week_labels()
        rows = []
        for origin_week in [f"2026-W{week:02d}" for week in range(16, 42)]:
            index = labels.index(origin_week)
            for horizon in (1, 2, 3):
                rows.append({
                    "design": "RETROSPECTIVE_UPDATED_VINTAGE_P2",
                    "origin_week": origin_week,
                    "training_start_week": labels[0],
                    "training_cutoff_week": origin_week,
                    "target_week": labels[index + horizon],
                    "horizon_weeks": horizon,
                    "node_count": q1.p2.NODE_COUNT,
                    "expected_node_horizon_rows": q1.p2.NODE_COUNT,
                })
        origins = q1.verify_design(pd.DataFrame(rows), labels)
        self.assertEqual(len(origins), 78)
        self.assertEqual(origins["origin_week"].nunique(), 26)
        self.assertEqual(origins["horizon"].tolist()[:3], [1, 2, 3])

    def test_spatial_moran_diagnostic_is_finite_for_a_synthetic_graph(self) -> None:
        values = np.asarray([1.0, 0.0, 1.0, 0.0])
        source = np.asarray([0, 1, 1, 2, 2, 3, 0, 1, 2, 3])
        target = np.asarray([1, 0, 2, 1, 3, 2, 3, 3, 0, 1])
        statistic = q1.spatial_moran(values, source, target)
        self.assertTrue(np.isfinite(statistic))
        pvalue = q1.spatial_permutation_p(values, source, target, seed=20261017, n_permutations=19)
        self.assertGreaterEqual(pvalue, 0.0)
        self.assertLessEqual(pvalue, 1.0)

    def test_proxy_threshold_table_uses_existing_limits_and_marks_scores_descriptive(self) -> None:
        rows = []
        for proxy in q1.PROXIES:
            for horizon in q1.HORIZONS:
                for index, observed in enumerate([0, 1, 0, 2, 0, 1]):
                    rows.append({
                        "proxy_id": proxy,
                        "horizon": horizon,
                        "observed_count": observed,
                        "observed_positive": int(observed > 0),
                        "p_occurrence": [0.15, 0.75, 0.20, 0.70, 0.10, 0.80][index],
                        "conditional_count_mean": 1.5,
                        "underlying_mu": 1.0,
                        "expected_count": 0.6,
                        "prediction_frontier_class": "previously_unoccupied" if index < 3 else "previously_occupied",
                    })
        result = q1.proxy_threshold_comparison(pd.DataFrame(rows))
        self.assertEqual(len(result), 2 * len(q1.HORIZONS))
        self.assertTrue(result["strict_pass_descriptive"].all())
        self.assertTrue(result["bounded_pass_descriptive"].all())
        self.assertTrue(result["comparison_status"].eq("DESCRIPTIVE_ONLY_UNCERTIFIED_TARGET_MATURITY").all())
        self.assertTrue(result["threshold_source"].str.contains("p7i_prespecification.md").all())

    def test_slurm_array_accounting_parses_task_and_batch_memory(self) -> None:
        rows = resources.parse_sacct_output(
            "21299859_0|stgnn-w44-q1-origin|COMPLETED|00:00:10||0:0\n"
            "21299859_0.batch|batch|COMPLETED|00:00:10|647.50M|0:0\n"
        )
        task = resources.task_accounting(rows, "21299859", 0)
        self.assertEqual(task["slurm_job_id"], "21299859_0")
        self.assertEqual(task["slurm_state"], "COMPLETED")
        self.assertAlmostEqual(task["slurm_max_rss_kib"], 647.5 * 1024)
        self.assertEqual(resources.parse_array_spec("21299867:1-3,5"), ("21299867", [1, 2, 3, 5]))


if __name__ == "__main__":
    unittest.main()
