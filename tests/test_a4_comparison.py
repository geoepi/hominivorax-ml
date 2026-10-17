"""Contract tests for the controlled A4 comparison."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "analysis" / "structured_a4_comparison" / "config" / "a4_comparison_config.json"
SCRIPT = ROOT / "analysis" / "structured_a4_comparison" / "scripts" / "run_a4_comparison.py"
RESULTS = ROOT / "analysis" / "structured_a4_comparison" / "results"


def test_no_prospective_weeks_are_in_a4_folds_or_selection():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    excluded = set(config["development_period"]["excluded_prospective_weeks"])
    for fold in config["folds"]:
        assert fold["validation_end"] <= "2026-W16"
        assert fold["train_end"] <= "2026-W16"
        assert fold["validation_start"] not in excluded
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"prospective_data_loaded": False' in source
    assert '"prospective_selection_used": False' in source


def test_sit_covariates_are_explicitly_excluded():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert config["sit"]["included"] is False
    assert config["sit"]["status"] == "RESERVED_FUTURE_INTERVENTION_LAYER"
    assert all("sit" not in feature.lower() for feature in config.get("feature_order", []))


def test_fold_definitions_are_deterministic_and_temporally_ordered():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    expected = [
        (1, "2025-W01", "2025-W26", "2025-W27", "2025-W39"),
        (2, "2025-W01", "2025-W39", "2025-W40", "2025-W52"),
        (3, "2025-W01", "2025-W52", "2026-W01", "2026-W08"),
        (4, "2025-W01", "2026-W08", "2026-W09", "2026-W16"),
    ]
    observed = [(f["fold"], f["train_start"], f["train_end"], f["validation_start"], f["validation_end"]) for f in config["folds"]]
    assert observed == expected


def test_candidate_metrics_are_comparable_and_include_guardrail_fields():
    path = RESULTS / "a4_candidate_comparison.csv"
    if not path.exists():
        return
    frame = pd.read_csv(path)
    assert set(frame["candidate"]) >= {"A3", "A4-S", "A4-C", "A4-SC", "A4-O"}
    required = {"mean_fold_pr_auc", "worst_fold_pr_auc", "mean_brier_skill", "mean_joint_nll", "mean_count_nll", "occurrence_moran_i", "positive_count_moran_i", "us_median_positive_percentile", "us_top10_recall"}
    assert required.issubset(frame.columns)
    a4o = frame.loc[frame["candidate"] == "A4-O"].iloc[0]
    assert bool(a4o["selection_eligible"]) is False
    assert a4o["identifiability"] == "sensitivity_only"


def test_spatial_residual_summary_is_out_of_fold():
    path = RESULTS / "a4_spatial_residual_summary.csv"
    if not path.exists():
        return
    frame = pd.read_csv(path)
    assert set(frame["residual"]) >= {"occurrence", "positive_count", "combined_expected_count"}
    manifest = json.loads((ROOT / "analysis" / "structured_a4_comparison" / "provenance" / "a4_analysis_manifest.json").read_text(encoding="utf-8"))
    assert manifest["prospective_data_loaded"] is False
    assert manifest["prospective_selection_used"] is False


def test_observation_sensitivity_scenarios_are_predeclared_and_reproducible():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    expected = [0.5, 0.75, 1.0]
    assert config["a4_o"]["reporting_rate_scenarios"] == expected
    path = RESULTS / "a4_o_sensitivity.csv"
    if path.exists():
        frame = pd.read_csv(path)
        assert sorted(frame["reporting_rate"].unique().tolist()) == expected
        assert set(frame["identifiability"]) == {"sensitivity_only"}


def test_frozen_a3_baseline_is_marked_unchanged():
    path = ROOT / "analysis" / "structured_a4_comparison" / "provenance" / "a4_analysis_manifest.json"
    if not path.exists():
        return
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["canonical_baseline_sha"] == "fae2d0f08c72a018338b9359543cfd2b88d7d8e2"
    assert manifest["a3_baseline_unchanged"] is True
    assert manifest["sit_included"] is False


def test_required_static_figures_are_manifested():
    manifest_path = ROOT / "analysis" / "structured_a4_comparison" / "figures" / "figure_manifest.csv"
    if not manifest_path.exists():
        return
    frame = pd.read_csv(manifest_path)
    required = {"candidate_pr_auc", "candidate_brier_skill", "candidate_joint_nll", "candidate_count_observed_vs_predicted", "candidate_residual_moran_i", "residual_spatial_map", "us_top_k_capture", "extrapolative_regime_performance", "complexity_vs_performance"}
    assert set(frame["figure"]) >= required
    for stem in required:
        assert (ROOT / "analysis" / "structured_a4_comparison" / "figures" / f"{stem}.png").exists()
        assert (ROOT / "analysis" / "structured_a4_comparison" / "figures" / f"{stem}.pdf").exists()
