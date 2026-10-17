"""Contract tests for the provisional frozen A4-S challenger workflow."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "analysis/structured_a4s_deferred_validation/scripts/freeze_a4s_challenger.py"
EVALUATE = ROOT / "analysis/structured_a4s_deferred_validation/scripts/evaluate_frozen_a3_vs_a4s.py"
RULES = ROOT / "analysis/structured_a4s_deferred_validation/config/a3_vs_a4s_advancement_rules.yaml"
A3_MANIFEST = ROOT / "analysis/structured_a3_evaluation/results/frozen_a3_evaluation_manifest.json"
A3_SIDEcar = ROOT / "analysis/structured_a3_evaluation/results/frozen_a3_evaluation_manifest.json.sha256"
A4_MANIFEST = ROOT / "analysis/structured_a4s_deferred_validation/results/frozen_a4s_challenger_manifest.json"
A4_SIDEcar = ROOT / "analysis/structured_a4s_deferred_validation/results/frozen_a4s_challenger_manifest.json.sha256"


class A4SDeferredValidationContracts(unittest.TestCase):
    def test_boundary_and_exclusion_are_literal(self) -> None:
        source = FREEZE.read_text(encoding="utf-8")
        self.assertIn('FIT_END = "2026-W16"', source)
        self.assertIn('FREEZE_WEEK = "2026-W42"', source)
        self.assertIn('ELIGIBLE_WEEK = "2026-W43"', source)
        self.assertIn('PROSPECTIVE_WEEKS = tuple(f"2026-W{week:02d}" for week in range(30, 40))', source)
        self.assertIn("W30-W39", source)

    def test_no_sit_or_reporting_covariates_in_frozen_specification(self) -> None:
        source = FREEZE.read_text(encoding="utf-8")
        self.assertNotRegex(source, r"(?i)SIT[_ -]?(density|treated|timing|front|intensity)")
        self.assertIn('"reporting_effort_covariates_available": False', source)
        self.assertIn('"sit_covariates_included": False', source)

    def test_evaluator_requires_no_refit_and_has_no_optimizer_import(self) -> None:
        source = EVALUATE.read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--no-refit", action="store_true")', source)
        self.assertIn('if not args.no_refit:', source)
        self.assertNotIn("scipy.optimize", source)
        self.assertNotIn("from sklearn", source)

    def test_rules_are_preregistered_and_support_is_explicit(self) -> None:
        rules = RULES.read_text(encoding="utf-8")
        for token in ("status: PRE_REGISTERED_BEFORE_INDEPENDENT_EVALUATION", "minimum_eligible_weeks: 8", "minimum_positive_node_weeks_overall: 50", "minimum_us_positive_node_weeks: 25", "median_positive_percentile_allowed_degradation: 5.0", "occurrence_moran_reduction_required: 0.05"):
            self.assertIn(token, rules)

    def test_a3_manifest_sidecar_integrity(self) -> None:
        payload = A3_MANIFEST.read_bytes()
        actual = hashlib.sha256(payload).hexdigest()
        expected = A3_SIDEcar.read_text(encoding="utf-8").split()[0]
        self.assertEqual(actual, expected)
        manifest = json.loads(payload)
        self.assertEqual(manifest["model"]["id"], "STRUCTURED_A3")
        self.assertEqual(manifest["model"]["predictor_count"], 34)

    def test_sidecar_byte_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_bytes(b'{"status":"frozen"}\n')
            digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
            sidecar = manifest.with_name(manifest.name + ".sha256")
            sidecar.write_text(f"{digest}  {manifest.name}\n", encoding="utf-8")
            self.assertEqual(hashlib.sha256(manifest.read_bytes()).hexdigest(), sidecar.read_text(encoding="utf-8").split()[0])

    def test_frozen_a4s_manifest_sidecar_integrity(self) -> None:
        payload = A4_MANIFEST.read_bytes()
        actual = hashlib.sha256(payload).hexdigest()
        expected = A4_SIDEcar.read_text(encoding="utf-8").split()[0]
        self.assertEqual(actual, expected)
        manifest = json.loads(payload)
        self.assertEqual(manifest["model"]["id"], "STRUCTURED_A4S_CHALLENGER")
        self.assertEqual(manifest["model"]["predictor_count"], 34)
        self.assertTrue(manifest["evaluation_restrictions"]["no_refit_after_freeze"])
        self.assertEqual(manifest["artifact"]["graph_sha256"], manifest["inputs"]["edges"]["sha256"])


if __name__ == "__main__":
    unittest.main()
