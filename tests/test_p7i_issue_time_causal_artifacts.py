"""Standard-library checks for the committed P7I validation artifacts.

These checks intentionally validate the compact, committed evidence contract;
they do not rerun the Atlas replay or fit any model.
"""

from __future__ import annotations

import ast
import csv
import json
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RESULT_ROOT = REPOSITORY_ROOT / "analysis" / "p7i_issue_time_validation" / "results"
DECISION_PATH = RESULT_ROOT / "decision.json"


class P7IIssueTimeCausalArtifactTests(unittest.TestCase):
    def test_prespecification_and_required_outputs_exist(self) -> None:
        prespec = REPOSITORY_ROOT / "analysis" / "p7i_issue_time_validation" / "p7i_prespecification.md"
        report = REPOSITORY_ROOT / "analysis" / "p7i_issue_time_validation" / "p7i_issue_time_validation_report.md"
        self.assertTrue(prespec.exists())
        self.assertTrue(report.exists())
        prespec_text = prespec.read_text(encoding="utf-8")
        self.assertIn("V4_ISSUE_TIME_CAUSAL", prespec_text)
        self.assertIn("E0_LAST_AVAILABLE", prespec_text)
        self.assertIn("target-week block bootstrap", prespec_text)
        required = {
            "variant_metrics.csv",
            "paired_variant_differences.csv",
            "paired_bootstrap_intervals.csv",
            "frontier_metrics.csv",
            "frontier_benchmark_topk.csv",
            "paired_first_detection_trajectory.csv",
            "support_metrics.csv",
            "v1_v2_equivalence.csv",
            "predictor_dependence_reconciliation.csv",
            "p4_coefficient_stability_reconciliation.json",
            "early_warning_metadata_reconciliation.json",
            "data_source_provenance.csv",
            "p7i_provenance_manifest.json",
        }
        self.assertTrue(all((RESULT_ROOT / name).exists() for name in required))

    def test_decision_manifest_records_causal_replay(self) -> None:
        payload = json.loads(DECISION_PATH.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "COMPLETED")
        self.assertEqual(payload["origin_count"], 21)
        self.assertEqual(payload["origins"][0], "2026-W16")
        self.assertEqual(payload["origins"][-1], "2026-W36")
        self.assertEqual(payload["horizons"], [1, 2, 3])
        self.assertTrue(payload["no_model_fitting"])
        self.assertTrue(payload["no_future_detection_sets_used_in_v4"])
        self.assertFalse(payload["target_outcomes_used_in_feature_construction"])
        self.assertEqual(payload["v3_status"], "COMPUTED_REALIZED_ENVIRONMENT_WITH_ORIGIN_BOUNDED_HISTORY")

    def test_variant_metrics_cover_four_variants_and_three_horizons(self) -> None:
        with (RESULT_ROOT / "variant_metrics.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 12)
        variants = {row["variant"] for row in rows}
        self.assertEqual(
            variants,
            {
                "V1_REALIZED_RETROSPECTIVE",
                "V2_E0_RETROSPECTIVE_HISTORY",
                "V3_REALIZED_ORIGIN_BOUNDED_HISTORY",
                "V4_ISSUE_TIME_CAUSAL",
            },
        )
        self.assertEqual({row["horizon"] for row in rows}, {"1", "2", "3"})
        self.assertEqual({int(row["n"]) for row in rows}, {210777})

    def test_v1_v2_equivalence_is_within_tolerance(self) -> None:
        with (RESULT_ROOT / "v1_v2_equivalence.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 21)
        for row in rows:
            self.assertEqual(int(row["v2_support_mismatches"]), 0)
            for field in ("v1_max_abs_difference", "v2_max_abs_difference"):
                values = ast.literal_eval(row[field])
                self.assertLessEqual(max(values.values()), 1e-10)

    def test_bootstrap_and_reconciliation_contracts(self) -> None:
        with (RESULT_ROOT / "paired_bootstrap_intervals.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertTrue(rows)
        self.assertEqual({int(row["bootstrap_replicates"]) for row in rows}, {199})
        self.assertEqual({row["block_unit"] for row in rows}, {"target_week"})

        p4 = json.loads((RESULT_ROOT / "p4_coefficient_stability_reconciliation.json").read_text(encoding="utf-8"))
        self.assertEqual(p4["status"], "CANONICAL_RETAINED_ARTIFACT_VERIFIED")
        self.assertFalse(p4["manuscript_intervals_added"])
        self.assertEqual(p4["model_hash"], "8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e")


if __name__ == "__main__":
    unittest.main()
