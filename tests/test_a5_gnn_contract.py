"""Focused contract tests for the bounded A5-GNN challenger."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "analysis/a5_gnn_bounded_comparison/scripts/a5_model.py"
CONFIG_PATH = ROOT / "analysis/a5_gnn_bounded_comparison/config/a5_gnn_config.json"
RUNNER_PATH = ROOT / "analysis/a5_gnn_bounded_comparison/scripts/run_a5_gnn.py"


try:
    spec = importlib.util.spec_from_file_location("a5_model_contract", MODEL_PATH)
    if spec is None or spec.loader is None:
        raise ImportError("could not load a5_model.py")
    a5_model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(a5_model)
    TORCH_IMPORT_ERROR = None
except ImportError as exc:  # pragma: no cover - exercised only on runtimes without torch
    a5_model = None
    TORCH_IMPORT_ERROR = str(exc)


class A5StaticContractTests(unittest.TestCase):
    def test_prespecification_config_contract(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(config["canonical_start_sha"], "6715a4397dad21a77414bd2ce41586751290f374")
        self.assertEqual(config["development_period"]["start"], "2025-W01")
        self.assertEqual(config["development_period"]["end"], "2026-W16")
        self.assertEqual(config["seeds"], [1729, 31415, 271828])
        self.assertEqual(config["model"]["theta"], 0.7018903965556372)
        self.assertEqual(config["model"]["loss"], "exact_joint_hurdle_nll")
        self.assertEqual(config["candidates"], ["A3", "STRUCTURED_A4S_CHALLENGER", "A5-PE", "A5-GNN-NOPE", "A5-GNN"])
        self.assertEqual(config["storage"]["output_root_env"], "A5_GNN_OUTPUT_ROOT")
        self.assertEqual(config["storage"]["temporary_storage_class"], "TEMPORARY_90DAY_STORAGE")

    def test_runner_does_not_read_outcomes_when_building_features(self) -> None:
        source = RUNNER_PATH.read_text(encoding="utf-8")
        start = source.index("def build_input(")
        end = source.index("\ndef train_model(", start)
        build_input = source[start:end]
        self.assertNotIn("fold.counts", build_input)
        self.assertNotIn("targets", build_input)
        self.assertIn("fold.eta", build_input)
        self.assertIn("fold.xi", build_input)

    def test_storage_paths_are_explicit_and_checkpointed(self) -> None:
        source = RUNNER_PATH.read_text(encoding="utf-8")
        self.assertIn("A5_GNN_OUTPUT_ROOT", source)
        self.assertIn("A5_GNN_DURABLE_SUMMARY_ROOT", source)
        self.assertIn("write_checkpoint_atomic", source)
        self.assertIn("load_completed_checkpoint", source)
        self.assertIn("TEMPORARY_90DAY_STORAGE", source)
        self.assertIn("state = AUG.fit_fixed_theta(x_train, y_train)", source)
        self.assertIn("load_frozen_a3_state", source)
        self.assertIn("--a3-frozen-output", source)

    @unittest.skipIf(a5_model is None, f"torch/scipy model dependencies unavailable: {TORCH_IMPORT_ERROR}")
    def test_exact_hurdle_loss_matches_numpy_reference(self) -> None:
        import torch

        count = np.array([0, 1, 4, 0, 2], dtype=np.float64)
        occurrence = np.array([-1.0, 0.5, 1.2, -0.2, 0.1], dtype=np.float64)
        log_mean = np.array([-0.7, 0.2, 1.0, -0.4, 0.6], dtype=np.float64)
        expected = a5_model.exact_joint_hurdle_nll_numpy(count, occurrence, log_mean)
        observed = a5_model.exact_joint_hurdle_nll(
            torch.as_tensor(count, dtype=torch.float64),
            torch.as_tensor(occurrence, dtype=torch.float64),
            torch.as_tensor(log_mean, dtype=torch.float64),
        )
        self.assertAlmostEqual(float(observed), expected, places=10)

    @unittest.skipIf(a5_model is None, f"torch/scipy model dependencies unavailable: {TORCH_IMPORT_ERROR}")
    def test_graph_edges_are_sorted_bidirectional_and_shells_are_exact(self) -> None:
        source, target = a5_model.canonical_directed_edges([2, 1, 0, 0, 1], [1, 0, 1, 0, 2], 4)
        self.assertEqual(list(zip(source.tolist(), target.tolist())), [(0, 1), (1, 0), (1, 2), (2, 1)])
        adjacency = coo_matrix((np.ones(4), ([0, 1, 1, 2], [1, 0, 2, 1])), shape=(4, 4)).tocsr()
        shells = a5_model.deterministic_spatial_shells(adjacency, 3)
        self.assertEqual(set(zip(*shells[1].nonzero())), {(0, 1), (1, 0), (1, 2), (2, 1)})
        self.assertEqual(set(zip(*shells[2].nonzero())), {(0, 2), (2, 0)})
        self.assertEqual(shells[3].nnz, 0)

    @unittest.skipIf(a5_model is None, f"torch/scipy model dependencies unavailable: {TORCH_IMPORT_ERROR}")
    def test_seed_setting_is_repeatable(self) -> None:
        import torch

        a5_model.set_seed(1729)
        first = torch.rand(7)
        a5_model.set_seed(1729)
        second = torch.rand(7)
        self.assertTrue(torch.equal(first, second))


if __name__ == "__main__":
    unittest.main()
