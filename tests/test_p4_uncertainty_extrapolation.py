"""Focused contracts for the P4 uncertainty/support workflow."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
P4_SOURCE = REPO_ROOT / "analysis" / "p4_uncertainty_extrapolation" / "scripts" / "run_p4_uncertainty_extrapolation.py"
P4_PRESPEC = REPO_ROOT / "analysis" / "p4_uncertainty_extrapolation" / "p4_prespecification.md"


def _load_p4():
    spec = importlib.util.spec_from_file_location("p4_uncertainty_extrapolation", P4_SOURCE)
    module = importlib.util.module_from_spec(spec)
    try:
        assert spec.loader is not None
        spec.loader.exec_module(module)
    except ModuleNotFoundError:
        return None
    return module


def test_p4_prespecification_is_training_only_and_bounded() -> None:
    text = P4_PRESPEC.read_text(encoding="utf-8")
    assert "Evaluation rows are never used to estimate a mean, scale, quantile," in text
    assert "BOOTSTRAP" not in text or "100 successful replicates" in text
    assert "SUPPORTED" in text and "CAUTION" in text and "EXTRAPOLATIVE" in text
    assert "No observed outcome is used to assign" in text


def test_p4_source_preserves_frozen_fitter_and_canonical_predictions() -> None:
    text = P4_SOURCE.read_text(encoding="utf-8")
    assert "fit_fixed_theta" in text
    assert "FEATURE_ORDER" in text
    assert "canonical_predictions_replaced" in text
    assert "BOOTSTRAP_BASE_SEED = 20261029" in text
    assert "complete training week" in text


def test_exact_hurdle_interval_contract_when_scientific_runtime_is_available() -> None:
    p4 = _load_p4()
    if p4 is None:
        return
    values = p4.hurdle_predictive_distribution(np.asarray([0.0, 0.25, 1.0]), np.asarray([1.0, 2.0, 4.0]))
    assert np.all(values["occurrence_predictive_variance"] >= 0)
    assert np.all(values["full_q025"] <= values["full_q975"])
    assert values["full_q025"][0] == 0
    assert np.all(np.isfinite(values["conditional_predictive_mean"]))
