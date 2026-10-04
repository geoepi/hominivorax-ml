#!/usr/bin/env python3
"""Finalize Task 3B documentation and provenance after the CPU fit."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_sha(repo: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


def git_branch(repo: Path) -> str:
    return subprocess.check_output(["git", "branch", "--show-current"], cwd=repo, text=True).strip()


def fmt(value) -> str:
    if pd.isna(value):
        return "NA"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("/project/disease_ecology/STGNN-output/v2_model"))
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--prior-jobs", default="20844276,20844278,20844279")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    output = args.output
    decisions = json.loads((output / "metrics" / "task3b_decisions.json").read_text())
    manifest_path = output / "manifests" / "task3b_v2a_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    dev = pd.read_csv(output / "metrics" / "development_summary_folds1_4.csv").set_index("model")
    pseudo = pd.read_csv(output / "metrics" / "historical_pseudoprospective_summary_folds5_6.csv").set_index("model")
    v1 = pd.read_csv(output / "metrics" / "v1_reproduction.csv")
    ranks = pd.read_csv(output / "metrics" / "new_cell_ranking_summary.csv")
    selected = pd.read_csv(output / "metrics" / "selected_penalty_metrics.csv")
    prior_jobs = [value.strip() for value in args.prior_jobs.split(",") if value.strip()]
    manifest.update({
        "git_sha": git_sha(repo),
        "branch": git_branch(repo),
        "v2_specification_frozen_date": "2026-10-03",
        "finalized_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "optimizer_settings": decisions.get("optimizer_settings", {}),
        "model_selection_criteria": decisions.get("model_selection_criteria", {}),
        "slurm_jobs": {
            "prior_attempts": prior_jobs,
            "completed_v2a_cpu_workflow": str(args.job_id),
        },
        "finalization_status": "complete_after_metric_and_schema_review",
    })
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rows = []
    for model in ["M0", "M1", "M2"]:
        row = dev.loc[model]
        rows.append(f"| {model} | {fmt(row['mean_joint_hurdle_nll'])} | {fmt(row['mean_brier_skill'])} | {fmt(row['mean_pr_auc'])} | {fmt(row['mean_positive_count_mae'])} |")
    pseudo_rows = []
    for model in ["M0", "M1", "M2"]:
        row = pseudo.loc[model]
        pseudo_rows.append(f"| {model} | {fmt(row['mean_joint_hurdle_nll'])} | {fmt(row['mean_brier_skill'])} | {fmt(row['mean_pr_auc'])} | {fmt(row['mean_positive_count_mae'])} |")
    rank_lines = []
    for model in ["M0", "M1", "M2"]:
        sub = ranks[(ranks.model == model) & ranks.fold.isin([1, 2, 3, 4])]
        rank_lines.append(f"| {model} | {fmt(sub.median_percentile_rank.mean())} | {fmt(sub.fraction_at_least_75.mean())} | {fmt(sub.fraction_at_least_90.mean())} |")
    selection = "\n".join(rows)
    pseudo_selection = "\n".join(pseudo_rows)
    rank_table = "\n".join(rank_lines)
    doc = f"""# Task 3B — V2-A Model Development and Selection

V2-A was evaluated as a historical development experiment. It models recorded detections conditional on current covariates and prior recorded detections; it does not estimate occupancy, detection probability, abundance, or biological dispersal. The former V1 terminal period is historical evaluated data, not an unseen test.

## Decision

- V2-A decision: **{decisions['v2a_decision']}**
- Latitude ablation: **{decisions['latitude_ablation_decision']}**
- Selected penalties: `{json.dumps(decisions['selected_penalties'], sort_keys=True)}`
- Predictive models outside V2-A fitted: **NO**
- Neural models fitted: **NO**

Selection used Folds 1–4 only. M0 remained fixed at penalty 0. M1 and M2 used only the authorized grid and were selected by mean Folds 1–4 joint hurdle NLL, then Brier skill and smaller penalty as tie-breakers. Folds 5–6 are historical pseudo-prospective and non-independent.

## Development summary — Folds 1–4

| Model | Mean joint NLL | Mean Brier skill | Mean PR-AUC | Mean positive-count MAE |
|---|---:|---:|---:|---:|
{selection}

## Historical pseudo-prospective summary — Folds 5–6

| Model | Mean joint NLL | Mean Brier skill | Mean PR-AUC | Mean positive-count MAE |
|---|---:|---:|---:|---:|
{pseudo_selection}

## First-ever positive localization — Folds 1–4

| Model | Median percentile | Fraction >=75th | Fraction >=90th |
|---|---:|---:|---:|
{rank_table}

The full case-level ranks, first-ever versus recurrent count summaries, calibration by prior-history state, front-distance strata, geographic transfer diagnostics, coefficient stability, and collinearity are in `STGNN-output/v2_model/metrics/`.

## V1 reproduction

The M0 reproduction is recorded in `metrics/v1_reproduction.csv`; the absolute joint-NLL and Brier-skill differences against the persisted Task 2F reference are expected to be within numerical tolerance. The response contract uses the immutable V1 target array. A small source-classification versus V1-target reconciliation is documented in the manifest because the earlier classification table and preflight assignment differ for a small number of response cells.

## Validation policy

Development specification-freeze date: **2026-10-03**. No currently available 2025–2026 observations qualify as a genuinely unseen V2 test. Observations arriving after this date form the first genuinely independent V2 evaluation period; V2-A remains a development-frozen candidate, not a validated final production model.
"""
    (repo / "docs" / "TASK3B_V2A_MODEL_SELECTION.md").write_text(doc, encoding="utf-8")
    history = repo / "docs" / "MODEL_DEVELOPMENT_HISTORY.md"
    history_text = history.read_text(encoding="utf-8")
    marker = "| 3B | V2-A causal front-state hurdle development |"
    if marker not in history_text:
        suffix = f"\n| 3B | V2-A causal front-state hurdle development | {decisions['v2a_decision']} | Historical rolling-origin development; latitude ablation {decisions['latitude_ablation_decision']}; no unseen V2 test. |\n"
        history.write_text(history_text.rstrip() + suffix, encoding="utf-8")
    checksum_rows = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "task3b_v2a_checksums.csv":
            checksum_rows.append({"relative_path": str(path.relative_to(output)), "size_bytes": path.stat().st_size, "sha256": sha256(path)})
    pd.DataFrame(checksum_rows).to_csv(output / "manifests" / "task3b_v2a_checksums.csv", index=False)
    print(json.dumps({"status": "finalized", "git_sha": manifest["git_sha"], "decision": decisions["v2a_decision"], "latitude": decisions["latitude_ablation_decision"]}, indent=2))


if __name__ == "__main__":
    main()
