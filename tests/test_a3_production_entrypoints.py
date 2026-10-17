"""Static contract tests for the Structured A3 production adapters."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINTS = {
    "P0": REPO_ROOT / "scripts" / "a3_preflight.py",
    "P1": REPO_ROOT / "scripts" / "a3_preprocess.py",
    "P2": REPO_ROOT / "scripts" / "a3_fit.py",
    "P3": REPO_ROOT / "scripts" / "a3_score.py",
    "P4": REPO_ROOT / "scripts" / "a3_products.py",
    "P5": REPO_ROOT / "scripts" / "a3_finalize.py",
}


class A3ProductionEntrypointTests(unittest.TestCase):
    def test_all_entrypoints_parse(self) -> None:
        for stage, path in ENTRYPOINTS.items():
            self.assertTrue(path.exists(), stage)
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        front = REPO_ROOT / "scripts" / "build_a3_front_features.py"
        ast.parse(front.read_text(encoding="utf-8"), filename=str(front))

    def test_wrappers_do_not_define_a_second_fit(self) -> None:
        for stage, path in ENTRYPOINTS.items():
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("fit_fixed_theta(", source, stage)
            self.assertNotIn("minimize(", source, stage)

    def test_atlas_template_uses_repository_entrypoints(self) -> None:
        template = (REPO_ROOT / "config" / "atlas-production.example.yaml").read_text(encoding="utf-8")
        for path in ENTRYPOINTS.values():
            self.assertIn(path.name, template)
        self.assertIn("--no-refit", template)
        self.assertNotIn("/STGNN-production-config/a3_", template)

    def test_full_fit_and_front_builder_are_horizon_general(self) -> None:
        fullfit = (REPO_ROOT / "analysis" / "structured_a3_fullfit" / "scripts" / "run_fullfit_products.py").read_text(encoding="utf-8")
        front = (REPO_ROOT / "scripts" / "build_a3_front_features.py").read_text(encoding="utf-8")
        self.assertIn("len(labels)", fullfit)
        self.assertNotIn("EXPECTED_RESPONSE_WEEKS", fullfit)
        for historical_constant in ("EXPECTED_SOURCE_SHA", "EXPECTED_SOURCE_ROWS", "2026-W29", "2026-07-19"):
            self.assertNotIn(historical_constant, front)

    def test_prospective_score_creates_prediction_directory(self) -> None:
        source = (REPO_ROOT / "scripts" / "a3_score.py").read_text(encoding="utf-8")
        self.assertIn('(output / "predictions").mkdir(parents=True, exist_ok=True)', source)

    def test_prospective_score_requires_frozen_training_prevalence(self) -> None:
        source = (REPO_ROOT / "scripts" / "a3_score.py").read_text(encoding="utf-8")
        self.assertIn('if "training_prevalence" not in model:', source)
        self.assertIn("training_prevalence required for prospective Brier-skill evaluation", source)
        self.assertIn("shape = (len(eligible), module.NODE_COUNT)", source)
        self.assertIn("mu = mu.reshape(shape)", source)


if __name__ == "__main__":
    unittest.main()
