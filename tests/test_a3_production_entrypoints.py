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


if __name__ == "__main__":
    unittest.main()
