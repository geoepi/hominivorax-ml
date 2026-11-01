"""Focused A5B contract tests; full fitting runs on Atlas."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
CONFIG_PATH = ROOT / "analysis/a5b_multiscale_component_spatial_ml/config/a5b_config.json"
RUNNER_PATH = ROOT / "analysis/a5b_multiscale_component_spatial_ml/scripts/run_a5b.py"
MODEL_PATH = ROOT / "analysis/a5b_multiscale_component_spatial_ml/scripts/a5b_model.py"


class A5BContractTests(unittest.TestCase):
    def test_configuration_is_development_informed_and_bounded(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(config["development_classification"], "DEVELOPMENT_INFORMED_FOLLOWUP")
        self.assertEqual(config["parent_a5_commit"], "e71c02c3ea87a4ab13dbb7733277c17b9c53c550")
        self.assertEqual(config["development_period"]["end"], "2026-W16")
        self.assertEqual(config["model"]["shell_count"], 4)
        self.assertEqual(config["model"]["shell_hidden_dim"], 8)
        self.assertEqual(config["seeds"], [1729, 31415, 271828])
        self.assertEqual(config["candidates"], ["STRUCTURED_A3", "STRUCTURED_A4S_CHALLENGER", "A5-GNN-NOPE", "A5B-MS-OCC", "A5B-HYBRID"])

    def test_immutable_reference_contracts_are_recorded(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(config["production_artifact_sha256"], "8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e")
        self.assertEqual(config["frozen_a4s_manifest_sha256"], "156ab650b8fa79f7a4fe390f3687ca53212fbf37fb7e9963ba91b9f70c9b68af")
        self.assertEqual(config["graph"]["canonical_edge_sha256"], "539876a1528c84f2bf7ab97f5b8f20b3da480cb1c705ac47611542e4a00ad9a7")
        a5_decision = json.loads((ROOT / "analysis/a5_gnn_bounded_comparison/results/a5_decision.json").read_text(encoding="utf-8"))
        self.assertEqual(a5_decision["primary_decision"], "A5_GNN_NOT_SUPPORTED")

    def test_storage_and_leakage_contracts_are_explicit(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(config["storage"]["temporary_storage_class"], "TEMPORARY_90DAY_STORAGE")
        self.assertIn("same_week_outcomes", config["forbidden"]["inputs"])
        self.assertIn("future_outcomes", config["forbidden"]["inputs"])
        self.assertIn("longitude_latitude", config["forbidden"]["inputs"])
        self.assertIn("laplacian_positional_encoding", config["forbidden"]["inputs"])
        source = RUNNER_PATH.read_text(encoding="utf-8")
        self.assertIn("positional_encoding_used", source)
        self.assertIn("masked_center_tensor", source)
        self.assertIn("occurrence_component_of_exact_joint_hurdle_nll", CONFIG_PATH.read_text(encoding="utf-8"))

    def test_multiscale_model_has_four_shell_operators(self) -> None:
        try:
            sys.path.insert(0, str(MODEL_PATH.parent))
            from a5b_model import MultiscaleOccurrenceResidualModel  # type: ignore
            import torch
        except Exception as exc:  # pragma: no cover - environment-dependent skip
            self.skipTest(f"torch unavailable: {exc}")
        model = MultiscaleOccurrenceResidualModel(36, 4, 8, 8, 0.1)
        self.assertEqual(len(model.shell_layers), 4)
        x = torch.zeros((5, 36), dtype=torch.float32)
        sources = [torch.tensor([0, 1, 2, 3], dtype=torch.long) for _ in range(4)]
        targets = [torch.tensor([1, 2, 3, 4], dtype=torch.long) for _ in range(4)]
        degrees = [torch.ones(5, dtype=torch.float32) for _ in range(4)]
        self.assertEqual(tuple(model(x, sources, targets, degrees).shape), (5,))


if __name__ == "__main__":
    unittest.main()
