"""Focused contracts for the diagnostic-only Structured A3 analysis."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.structured_a3_prospective_diagnostics.scripts.run_diagnostics import (
    EXPECTED_WEEKS,
    add_tolerance_rows,
    reliability_rows,
    safe_subset_metrics,
    us_risk_ranking,
)


def test_exact_prospective_week_boundary() -> None:
    assert EXPECTED_WEEKS == [f"2026-W{week:02d}" for week in range(30, 40)]
    assert len(EXPECTED_WEEKS) == 10


def test_safe_metrics_flags_single_class_strata() -> None:
    frame = pd.DataFrame(
        {
            "observed_count": [0, 0, 0],
            "p_occurrence": [0.01, 0.02, 0.03],
            "conditional_count_mean": [1.0, 1.0, 1.0],
            "underlying_mu": [0.1, 0.2, 0.3],
            "expected_count": [0.01, 0.02, 0.03],
        }
    )

    def evaluator(*args, **kwargs):
        raise AssertionError("the hurdle evaluator is not needed for an all-negative stratum")

    result = safe_subset_metrics(frame, 0.018, 0.7, evaluator)
    assert np.isnan(result["pr_auc"])
    assert np.isnan(result["roc_auc"])
    assert result["calibration_flag"] == "not_estimable_single_class"


def test_calibration_bins_are_reproducible_and_cover_rows() -> None:
    p = np.array([0.01, 0.01, 0.02, 0.04, 0.10, 0.20, 0.80, 0.90])
    y = np.array([0, 1, 0, 0, 1, 0, 1, 1])
    first = reliability_rows(p, y, "full_domain", "equal_frequency")
    second = reliability_rows(p, y, "full_domain", "equal_frequency")
    assert first == second
    assert sum(row["n"] for row in first) == len(p)


def test_us_rank_calculation_is_deterministic() -> None:
    rows = []
    for week in ["2026-W30", "2026-W31"]:
        for node, probability, count in [(0, 0.90, 1), (1, 0.70, 0), (2, 0.20, 0), (3, 0.01, 0)]:
            rows.append({
                "week": week,
                "model_node_id": node,
                "country_or_domain_region": "U.S.-to-40N",
                "p_occurrence": probability,
                "observed_count": count,
            })
    data = {"predictions": pd.DataFrame(rows)}
    first = us_risk_ranking(data)
    second = us_risk_ranking(data)
    pd.testing.assert_frame_equal(first, second)
    overall = first.loc[first["row_type"] == "overall_positive_summary"].iloc[0]
    assert overall["median_positive_risk_percentile"] == 100.0
    top_10 = first.loc[(first["row_type"] == "overall_top_k") & np.isclose(first["top_k"], 0.10)].iloc[0]
    assert top_10["recall"] == 1.0


def test_metric_reproduction_contract_has_zero_difference() -> None:
    authoritative = {
        "node_weeks": 4,
        "positive_node_weeks": 1,
        "prevalence": 0.25,
        "observed_total_detections": 2,
        "predicted_total_detections": 2.5,
        "metrics": {
            "brier": 0.1,
            "brier_skill": 0.2,
            "pr_auc": 0.3,
            "roc_auc": 0.4,
            "zt_nb_nll": 0.5,
            "joint_hurdle_nll": 0.6,
            "calibration_intercept": 0.7,
            "calibration_slope": 0.8,
        },
    }
    recomputed = {
        "n_node_weeks": 4,
        "positive_node_weeks": 1,
        "observed_prevalence": 0.25,
        "observed_detections": 2,
        "predicted_detections": 2.5,
        "brier": 0.1,
        "brier_skill": 0.2,
        "pr_auc": 0.3,
        "roc_auc": 0.4,
        "zt_nb_nll": 0.5,
        "joint_hurdle_nll": 0.6,
        "calibration_intercept": 0.7,
        "calibration_slope": 0.8,
    }
    result = add_tolerance_rows(authoritative, recomputed)
    assert result["pass"].all()
    assert float(result["absolute_difference"].max()) == 0.0


def test_diagnostic_source_has_no_refit_or_optimizer_imports() -> None:
    source_path = Path(__file__).parents[1] / "analysis" / "structured_a3_prospective_diagnostics" / "scripts" / "run_diagnostics.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    imported = ast.unparse(ast.Module(body=imports, type_ignores=[]))
    assert "scipy.optimize" not in imported
    assert "torch" not in imported
    assert "a3_fit" not in source
    assert "feature_selection" not in source


def test_outputs_are_separated_from_authoritative_inputs() -> None:
    source_path = Path(__file__).parents[1] / "analysis" / "structured_a3_prospective_diagnostics" / "scripts" / "run_diagnostics.py"
    source = source_path.read_text(encoding="utf-8")
    assert "output_root / \"results" in source
    assert "output_root / \"figures" in source
    assert "write_csv(prospective_root" not in source
    assert "write_json(prospective_root" not in source
    assert "write_csv(model_root" not in source
    assert "write_json(model_root" not in source
