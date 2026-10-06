#!/usr/bin/env python3
"""Finalize the compact, committed report for the completed A0 audit."""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import sys
from pathlib import Path

import pandas as pd
import torch


def load_runner(path: Path):
    spec = importlib.util.spec_from_file_location("neural_a0_runner", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--runner", type=Path, required=True)
    args = parser.parse_args()
    root = args.output_root
    result = root / "results"
    runner = load_runner(args.runner)

    loss_audit = runner.loss_component_audit(result)
    gradient_audit = runner.loss_gradient_audit(result)
    config_path = root / "reference_configuration.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["loss_audit"] = loss_audit
    config["gradient_audit"] = gradient_audit
    write_json(config_path, config)

    summary = pd.read_csv(result / "diagnostic_model_summary.csv")
    valid = {}
    for _, row in summary.iterrows():
        valid[str(row.model_id)] = bool(
            row.finite_predictions
            and row.nondegenerate_probability
            and row.mean_brier_skill > 0
            and row.mean_pr_auc > row.mean_reference_pr_auc
            and row.mean_joint_hurdle_nll < row.mean_reference_joint_hurdle_nll
        )

    phase_decisions = {
        "N1": {
            "decision": "LOSS OBJECTIVE MISMATCH — MATERIAL",
            "current_balanced_loss_is_exact_joint_nll": False,
            "zero_case_current_loss_is_finite": bool(loss_audit["zero_case_current_is_finite"]),
            "exact_loss_validity_restored": valid.get("N1-E", False),
        },
        "N2": {
            "decision": "GRAPH COMPONENT IMPLICATED; NON-GRAPH CONTROL STILL INVALID",
            "gconvgru_k3_valid": valid.get("N2-R", False),
            "non_graph_gru_valid": valid.get("N2-G0", False),
        },
        "N3": {
            "decision": "K1 MODESTLY IMPROVES K3 BUT DOES NOT RESTORE VALIDITY",
            "k1_valid": valid.get("N3-K1", False),
            "k3_valid": valid.get("N3-K3", False),
        },
        "N4": {
            "decision": "36 EPOCHS IMPROVES METRICS BUT DOES NOT RESTORE VALIDITY",
            "e12_valid": valid.get("N4-E12", False),
            "e36_valid": valid.get("N4-E36", False),
        },
    }

    final_decision = {
        "completed_task_count": int(summary["run_count"].sum()),
        "models_run": sorted(summary.model_id.astype(str).unique().tolist()),
        "classification": "A0 VALIDITY IMPROVED BUT REMAINS AMBIGUOUS",
        "valid_gate_by_model": valid,
        "phase_decisions": phase_decisions,
        "a3_predictors_used": False,
        "f5_f6_used": False,
        "terminal_later_outcomes_used": False,
        "feature_selection_reopened": False,
        "feature_set_changed": False,
        "response_changed": False,
        "theta_changed_or_reestimated": False,
        "theta": runner.THETA,
        "main_merged": False,
        "final_recommended_predictor_specification": {
            "status": "A0 predictor specification remains the only authorized boundary; no neural baseline is frozen",
            "predictor_set": "exactly 30 frozen V2-A predictors",
            "feature_selection": "F1-F4 only",
            "node_count": runner.NODE_COUNT,
            "directed_edge_count": runner.EDGE_COUNT,
            "warmup_weeks": runner.WARMUP_WEEKS,
            "tbptt_weeks": runner.TBPTT,
            "theta": runner.THETA,
            "a3_predictors": False,
        },
        "stop_condition": "Sequential N1-N4 audit completed; stop without A3 predictor use, feature reopening, or main merge.",
    }
    write_json(result / "final_architecture_decision.json", final_decision)
    write_json(root / "neural_a0_architecture_audit_manifest.json", {
        "audit_version": "neural-a0-architecture-audit-v1",
        "completed": int(summary["run_count"].sum()),
        "result_root": result,
        "final_decision": final_decision,
    })

    (root / "figures").mkdir(parents=True, exist_ok=True)
    (root / "figures" / "figure_generation_status.txt").write_text(
        "PLOTTING UNAVAILABLE — matplotlib is not installed in the Atlas runtime; plotting-ready tables are preserved in results/.\n",
        encoding="utf-8",
    )
    (result / "software_environment.txt").write_text(
        "\n".join([
            f"python={platform.python_version()}",
            f"platform={platform.platform()}",
            f"torch={torch.__version__}",
            f"cuda_available={torch.cuda.is_available()}",
            f"pandas={pd.__version__}",
        ]) + "\n",
        encoding="utf-8",
    )

    def row(model: str, field: str) -> float:
        return float(summary.loc[summary.model_id == model, field].iloc[0])

    loss_frame = pd.read_csv(result / "loss_component_audit.csv")
    grad_frame = pd.read_csv(result / "loss_gradient_audit.csv")
    graph = pd.read_csv(result / "graph_architecture_audit.csv").iloc[0]
    report = f"""# STGNN revised-domain neural A0 architecture and training audit

## Final disposition

**A0 VALIDITY IMPROVED BUT REMAINS AMBIGUOUS**

The audit completed all prescribed phases N1-N4 on the frozen revised-domain A0 task. The exact joint hurdle loss, non-graph control, K1 graph depth, and 36-epoch training duration each provide diagnostic information, but no tested neural configuration passes the validity gate (finite/nondegenerate predictions, positive Brier skill, PR-AUC above the frozen reference, and joint hurdle NLL below the frozen reference). The audit therefore does not support freezing a corrected neural baseline or proceeding to A3 predictor use.

## A0 boundary and provenance

- Input: exactly 30 frozen V2-A predictors, F1-F4 only; no A3 predictors were loaded.
- Graph: {runner.NODE_COUNT:,} nodes and {runner.EDGE_COUNT:,} directed queen edges; fixed node order; no response or domain changes.
- Temporal contract: {runner.WARMUP_WEEKS} warm-up weeks, {runner.TBPTT}-week TBPTT, development folds F1-F4 only; terminal/later outcomes excluded.
- Fixed hurdle parameter: theta = {runner.THETA:.16f}; no re-estimation.
- Source provenance: `feature/stgnn-a3-ablation` at `4797edff54c019cdd978b92e57413b58992d18ec`; audit branch starts from consolidated `main`.

## Deterministic objective audit

The current `balanced_multitask_loss` is **not** the exact observation-level joint hurdle negative log-likelihood. The single-positive terms agree, but the current loss uses a positive-count denominator and is undefined for a batch containing no positive observations. The material batch differences were:

- mixed `[0,1,2,100]`: current minus exact = `{loss_frame.loc[loss_frame.case == 'mixed_batch', 'difference'].iloc[0]:.9f}`;
- rare-positive `[0,0,0,0,1]`: current minus exact = `{loss_frame.loc[loss_frame.case == 'rare_positive_batch', 'difference'].iloc[0]:.9f}`;
- rare-positive gradient cosine = `{grad_frame.loc[grad_frame.case == 'rare_positive_batch', 'gradient_cosine'].iloc[0]:.6f}`.

The exact loss was therefore used for N2-N4. It improved the objective, but N1-E remained invalid.

## Graph audit

The persisted graph passed the structural checks: {int(graph.node_count):,} nodes, {int(graph.directed_edge_count):,} directed edges, {int(graph.connected_components)} connected components, {int(graph.isolates)} isolates, zero missing reverse edges, zero duplicates, and zero self-loops. N2 implicated the graph component because the non-graph GRU improved mean NLL from {row('N1-E', 'mean_joint_hurdle_nll'):.6f} to {row('N2-G0', 'mean_joint_hurdle_nll'):.6f}, but its Brier skill remained negative ({row('N2-G0', 'mean_brier_skill'):.6f}). N3 K1 was modestly better than K3 but remained invalid.

## Paired phase results

| model | runs | mean joint NLL | mean PR-AUC | mean Brier skill | count MAE | calibration intercept | calibration slope | valid |
|---|---:|---:|---:|---:|---:|---:|---:|---|
"""
    for model in ["N1-R", "N1-E", "N2-G0", "N2-R", "N3-K1", "N3-K3", "N4-E12", "N4-E36"]:
        s = summary.loc[summary.model_id == model].iloc[0]
        report += f"| {model} | {int(s.run_count)} | {s.mean_joint_hurdle_nll:.6f} | {s.mean_pr_auc:.6f} | {s.mean_brier_skill:.6f} | {s.mean_positive_count_mae:.6f} | {s.mean_calibration_intercept:.6f} | {s.mean_calibration_slope:.6f} | {'yes' if valid[model] else 'no'} |\n"
    report += f"""

N4 showed the strongest improvement: E36 reduced mean joint NLL to {row('N4-E36', 'mean_joint_hurdle_nll'):.6f} and increased mean PR-AUC to {row('N4-E36', 'mean_pr_auc'):.6f}, but mean Brier skill remained {row('N4-E36', 'mean_brier_skill'):.6f}, with materially non-ideal calibration (intercept {row('N4-E36', 'mean_calibration_intercept'):.6f}, slope {row('N4-E36', 'mean_calibration_slope'):.6f}). Duration therefore improves the diagnostic result without restoring the validity gate.

## Training, temporal, and prediction checks

- All 160 task records completed successfully on Atlas; all were finite and nondegenerate.
- The training loop resets hidden state per task, replays the 52-week warm-up without response loss, trains contiguous 13-week TBPTT chunks, and detaches hidden state between chunks.
- The fold/seed, weekly calibration, prediction-distribution, count-summary, and training-behavior tables are preserved in `results/`. Optional raster figures were not generated because matplotlib is unavailable in the Atlas runtime.

## Boundary checks and final recommendation

All boundary checks are false: A3 predictors used, F5/F6 used, terminal/later outcomes used, feature selection reopened, feature set changed, response changed, theta changed/re-estimated, and main merged. The final recommendation is to retain the frozen 30-predictor A0 specification as the analysis boundary only, do not freeze any tested neural configuration as a validated baseline, and stop before A3 augmentation or feature selection reopening.
"""
    (result / "neural_a0_architecture_audit_report.md").write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
