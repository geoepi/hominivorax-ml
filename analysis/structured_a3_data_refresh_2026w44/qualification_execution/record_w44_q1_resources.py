#!/usr/bin/env python3
"""Reconcile Atlas Slurm accounting with completed Q1 origin/horizon outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def rss_kib(value: str) -> float | None:
    value = value.strip()
    if not value or value in {"Unknown", "N/A"}:
        return None
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([KMGTP]?)", value)
    require(match is not None, f"unrecognized Slurm MaxRSS value: {value}")
    amount = float(match.group(1))
    unit = match.group(2) or "K"
    exponent = {"K": 0, "M": 1, "G": 2, "T": 3, "P": 4}[unit]
    return amount * (1024 ** exponent)


def parse_sacct_output(output: str) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("|")
        if parts[0] == "JobID":
            continue
        require(len(parts) >= 6, f"malformed sacct row: {line}")
        job_id, job_name, state, elapsed, max_rss, exit_code = parts[:6]
        rows[job_id] = {
            "job_id": job_id,
            "job_name": job_name,
            "state": state,
            "elapsed": elapsed,
            "max_rss": max_rss,
            "exit_code": exit_code,
        }
    return rows


def parse_array_spec(value: str) -> tuple[str, list[int]]:
    job_id, task_spec = value.split(":", maxsplit=1)
    tasks: list[int] = []
    for part in task_spec.split(","):
        if "-" in part:
            start, end = (int(piece) for piece in part.split("-", maxsplit=1))
            tasks.extend(range(start, end + 1))
        else:
            tasks.append(int(part))
    require(len(tasks) == len(set(tasks)), f"duplicate task IDs in array specification: {value}")
    return job_id, tasks


def sacct_rows(job_ids: list[str]) -> dict[str, dict[str, str]]:
    command = [
        "sacct", "-j", ",".join(job_ids),
        "--format=JobID,JobName,State,Elapsed,MaxRSS,ExitCode",
        "--parsable2", "--noheader",
    ]
    output = subprocess.check_output(command, text=True)
    return parse_sacct_output(output)


def task_accounting(rows: dict[str, dict[str, str]], array_id: str, task_id: int) -> dict[str, Any]:
    key = f"{array_id}_{task_id}"
    task = rows.get(key)
    batch = rows.get(f"{key}.batch")
    require(task is not None, f"Slurm task accounting is missing: {key}")
    require(batch is not None, f"Slurm batch-step accounting is missing: {key}.batch")
    return {
        "slurm_job_id": key,
        "slurm_array_job_id": array_id,
        "slurm_array_task_id": task_id,
        "slurm_state": task["state"],
        "slurm_elapsed": task["elapsed"],
        "slurm_max_rss": batch["max_rss"],
        "slurm_max_rss_kib": rss_kib(batch["max_rss"]),
        "slurm_exit_code": task["exit_code"],
    }


def job_accounting(rows: dict[str, dict[str, str]], job_id: str, purpose: str) -> dict[str, Any]:
    task = rows.get(job_id)
    batch = rows.get(f"{job_id}.batch")
    require(task is not None, f"Slurm job accounting is missing: {job_id}")
    return {
        "purpose": purpose,
        "slurm_job_id": job_id,
        "state": task["state"],
        "elapsed": task["elapsed"],
        "max_rss": batch["max_rss"] if batch else "",
        "max_rss_kib": rss_kib(batch["max_rss"]) if batch else None,
        "exit_code": task["exit_code"],
        "origin_week": "",
        "array_task_id": "",
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(args: argparse.Namespace) -> None:
    root = args.output_root
    results = args.results_root
    input_manifest = json.loads((root / "manifests/input_manifest.json").read_text(encoding="utf-8"))
    origin_manifest = pd.read_csv(root / "manifests/rolling_origin_manifest.csv")
    origins = origin_manifest[["slot", "origin_week"]].drop_duplicates().sort_values("slot")
    require(len(origins) == 26 and origins["slot"].astype(int).tolist() == list(range(26)), "origin manifest does not have the approved slots 0 through 25")

    successful_specs = [parse_array_spec(value) for value in args.successful_origin_array]
    failed_specs = [parse_array_spec(value) for value in args.failed_pilot_array]
    expected_success_tasks = {(job, task) for job, tasks in successful_specs for task in tasks}
    require(len(expected_success_tasks) == 26, f"expected 26 successful origin tasks, found {len(expected_success_tasks)}")
    require({task for _, task in expected_success_tasks} == set(range(26)), "successful Slurm arrays do not cover each approved origin slot exactly once")
    expected_failed_tasks = {(job, task) for job, tasks in failed_specs for task in tasks}
    all_job_ids = sorted({
        *args.prepare_job,
        *(job for job, _ in expected_success_tasks),
        *(job for job, _ in expected_failed_tasks),
        args.aggregate_job,
    })
    sacct = sacct_rows(all_job_ids)

    status_rows: list[dict[str, Any]] = []
    per_horizon_rows: list[dict[str, Any]] = []
    task_rows: list[dict[str, Any]] = []
    node_count = int(input_manifest["response_and_environment"]["node_count"])
    for job_id, task_id in sorted(expected_success_tasks, key=lambda pair: pair[1]):
        accounting = task_accounting(sacct, job_id, task_id)
        require(accounting["slurm_state"] == "COMPLETED" and accounting["slurm_exit_code"] == "0:0", f"origin task did not complete cleanly: {job_id}_{task_id}")
        week = str(origins.loc[origins["slot"].astype(int).eq(task_id), "origin_week"].iloc[0])
        status_path = root / f"manifests/origin_{week}.json"
        fit_path = root / f"fits/origin_{week}.json"
        prediction_path = root / f"predictions/origin_{week}.parquet"
        status = json.loads(status_path.read_text(encoding="utf-8"))
        fit = json.loads(fit_path.read_text(encoding="utf-8"))
        require(status.get("status") == "COMPLETED" and status.get("origin_week") == week, f"completed origin manifest mismatch: {week}")
        require(status.get("candidate_model_sha256") == input_manifest["candidate_model_sha256"], f"candidate hash mismatch: {week}")
        require(status.get("future_history_uses") == 0 and fit.get("future_history_uses") == 0, f"future history use recorded for {week}")
        require(status.get("fit_artifact_sha256") == sha256_file(fit_path), f"fit artifact hash mismatch: {week}")
        require(status.get("prediction_artifact_sha256") == sha256_file(prediction_path), f"prediction artifact hash mismatch: {week}")
        require(int(status.get("prediction_rows", -1)) == 9 * node_count, f"prediction row count mismatch: {week}")
        status_rows.append({"origin_week": week, **accounting, "origin_runtime_seconds": status["runtime_seconds"], "fit_sha256": status["fit_artifact_sha256"], "prediction_sha256": status["prediction_artifact_sha256"]})
        target_rows = origin_manifest.loc[origin_manifest["origin_week"].astype(str).eq(week)].sort_values("horizon")
        require(len(target_rows) == 3, f"origin horizon mapping incomplete: {week}")
        for row in target_rows.to_dict(orient="records"):
            per_horizon_rows.append({
                "origin_week": week,
                "target_week": str(row["target_week"]),
                "horizon": int(row["horizon"]),
                "training_cutoff_week": str(row["training_cutoff_week"]),
                "model_node_count": node_count,
                **accounting,
                "fit_sha256": status["fit_artifact_sha256"],
                "prediction_sha256": status["prediction_artifact_sha256"],
                "scoring_eligibility": "NOT_CERTIFIED_TARGET_MATURITY",
            })
        task_rows.append({
            "purpose": "successful_origin",
            "slurm_job_id": accounting["slurm_job_id"],
            "state": accounting["slurm_state"],
            "elapsed": accounting["slurm_elapsed"],
            "max_rss": accounting["slurm_max_rss"],
            "max_rss_kib": accounting["slurm_max_rss_kib"],
            "exit_code": accounting["slurm_exit_code"],
            "origin_week": week,
            "array_task_id": task_id,
        })

    require(len(per_horizon_rows) == 78, f"expected 78 origin-horizon resource rows; found {len(per_horizon_rows)}")
    summary_rows: list[dict[str, Any]] = []
    for job_id in args.prepare_job:
        summary_rows.append(job_accounting(sacct, job_id, "input_preparation"))
    for job_id in args.prepare_job:
        require(sacct[job_id]["state"] == "COMPLETED", f"input preparation job failed: {job_id}")
    summary_rows.extend(task_rows)
    for job_id, task_id in sorted(expected_failed_tasks):
        failed = task_accounting(sacct, job_id, task_id)
        require(failed["slurm_state"] == "FAILED", f"initial pilot task state changed: {job_id}_{task_id}")
        summary_rows.append({
            "purpose": "failed_pilot_attempt_preserved",
            "slurm_job_id": failed["slurm_job_id"],
            "state": failed["slurm_state"],
            "elapsed": failed["slurm_elapsed"],
            "max_rss": failed["slurm_max_rss"],
            "max_rss_kib": failed["slurm_max_rss_kib"],
            "exit_code": failed["slurm_exit_code"],
            "origin_week": str(origins.loc[origins["slot"].astype(int).eq(task_id), "origin_week"].iloc[0]),
            "array_task_id": task_id,
            "failure_reason": "Metadata provenance key mismatch after prediction write; partial outputs retained in attempt01 and excluded from Q1 scoring.",
        })
    summary_rows.append(job_accounting(sacct, args.aggregate_job, "aggregate_and_diagnostic_run"))

    results.mkdir(parents=True, exist_ok=True)
    origin_execution = pd.DataFrame(status_rows).sort_values("origin_week", kind="mergesort")
    horizon_execution = pd.DataFrame(per_horizon_rows).sort_values(["origin_week", "horizon"], kind="mergesort")
    job_summary = pd.DataFrame(summary_rows)
    origin_execution.to_csv(results / "origin_slurm_execution.csv", index=False)
    horizon_execution.to_csv(results / "origin_horizon_execution_manifest.csv", index=False)
    job_summary.to_csv(results / "q1_job_resource_summary.csv", index=False)

    report_path = results / "q1_retrospective_qualification_report.md"
    require(report_path.exists(), "Q1 aggregate report is missing")
    report = report_path.read_text(encoding="utf-8")
    marker = "<!-- Q1 Slurm resource reconciliation -->"
    report = report.split(marker)[0].rstrip()
    successful = origin_execution
    elapsed_seconds = pd.to_timedelta(successful["slurm_elapsed"]).dt.total_seconds()
    rss_values = successful["slurm_max_rss_kib"].dropna()
    q1_report = [
        marker,
        "",
        "## Slurm execution and resource reconciliation",
        "",
        f"All 26 origin fits and all 78 origin-horizon blocks completed successfully. The pilot array was `{','.join(job for job, _ in successful_specs if job == '21299859')}` for slots 0 and 25; the full remaining array was `{','.join(job for job, _ in successful_specs if job == '21299867')}` for slots 1–24.",
        f"Origin task elapsed time ranged from {elapsed_seconds.min():.0f} to {elapsed_seconds.max():.0f} seconds; peak batch-step MaxRSS ranged from {rss_values.min() / 1024:.1f} to {rss_values.max() / 1024:.1f} MiB. Per-origin and per-horizon Slurm IDs, elapsed time, memory, target keys, and artifact hashes are recorded in `origin_horizon_execution_manifest.csv`.",
        f"Input preparation jobs: {', '.join(args.prepare_job)}. Successful pilot array: {', '.join(job for job, _ in successful_specs if job == '21299859')}. Full origin array: {', '.join(job for job, _ in successful_specs if job == '21299867')}. Aggregate job: {args.aggregate_job}.",
        f"The first pilot attempt used job array {', '.join(job for job, _ in failed_specs)} and stopped on an execution-code metadata-key error after writing partial predictions. Its outputs remain preserved under the `attempt01` Atlas root and are excluded from this Q1 result. The successful pilot and full origins use the isolated `attempt02` root.",
        "",
        "The Q1 outcome maturity limitation still applies: all performance metrics are descriptive, and no qualification decision is assigned.",
        "",
    ]
    report_path.write_text(report + "\n" + "\n".join(q1_report), encoding="utf-8")

    manifest = {
        "status": "COMPLETED",
        "candidate_model_sha256": input_manifest["candidate_model_sha256"],
        "observation_source_sha256": input_manifest["observation_source_sha256"],
        "origin_count": len(origin_execution),
        "origin_horizon_block_count": len(horizon_execution),
        "successful_origin_array_jobs": args.successful_origin_array,
        "failed_pilot_array_jobs": args.failed_pilot_array,
        "prepare_job_ids": args.prepare_job,
        "aggregate_job_id": args.aggregate_job,
        "origin_execution_csv_sha256": sha256_file(results / "origin_slurm_execution.csv"),
        "origin_horizon_execution_csv_sha256": sha256_file(results / "origin_horizon_execution_manifest.csv"),
        "job_resource_summary_csv_sha256": sha256_file(results / "q1_job_resource_summary.csv"),
        "aggregate_report_sha256": sha256_file(report_path),
        "aggregate_results_path": str(results),
        "row_level_and_coordinate_data_committed": False,
    }
    (results / "q1_execution_resources_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "RESOURCE_RECONCILIATION_COMPLETED",
        "origins": len(origin_execution),
        "origin_horizon_blocks": len(horizon_execution),
        "origin_elapsed_seconds_min": float(elapsed_seconds.min()),
        "origin_elapsed_seconds_max": float(elapsed_seconds.max()),
        "origin_max_rss_kib_max": float(rss_values.max()),
        "aggregate_job_id": args.aggregate_job,
        "results": str(results),
    }, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--prepare-job", action="append", required=True)
    parser.add_argument("--successful-origin-array", action="append", required=True)
    parser.add_argument("--failed-pilot-array", action="append", required=True)
    parser.add_argument("--aggregate-job", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
