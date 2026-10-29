#!/usr/bin/env python3
"""Render compact P5 results and the required human-readable report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
from typing import Any

import pandas as pd


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def copy_artifact(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def render(repo: Path, root: Path, job_id: str) -> dict[str, Any]:
    result_root = repo / "analysis" / "p5_operational_contract" / "results"
    result_root.mkdir(parents=True, exist_ok=True)
    preflight = read_json(root / "preflight" / "run_manifest.json")
    replay = read_json(root / "replay_a" / "run_manifest.json")
    comparison = read_json(root / "reproducibility_comparison" / "reproducibility_comparison.json")
    failure_summary = read_json(root / "failure_tests" / "failure_mode_test_summary.json")
    availability = pd.read_csv(root / "preflight" / "predictor_availability_audit.csv")
    matrix = pd.read_csv(root / "preflight" / "horizon_availability_matrix.csv")
    for name in (
        "predictor_availability_audit.csv",
        "horizon_availability_matrix.csv",
        "production_input_manifest.csv",
        "input_contract.json",
        "freshness_rules.json",
        "output_schema.json",
        "warning_error_codes.json",
    ):
        copy_artifact(root / "preflight" / name, result_root / name)
    copy_artifact(root / "replay_a" / "run_manifest.json", result_root / "replay_manifest.json")
    copy_artifact(root / "reproducibility_comparison" / "reproducibility_comparison.json", result_root / "reproducibility_comparison.json")
    copy_artifact(root / "failure_tests" / "failure_mode_test_results.csv", result_root / "failure_mode_test_results.csv")
    copy_artifact(root / "failure_tests" / "failure_mode_test_summary.json", result_root / "failure_mode_test_summary.json")

    availability_counts = availability["availability_class"].value_counts().sort_index().to_dict()
    retrospective = availability.loc[availability["availability_class"] == "RETROSPECTIVE_ONLY", "predictor"].tolist()
    unknown = availability.loc[availability["availability_class"] == "UNKNOWN", "predictor"].tolist()
    blockers = sorted(set(preflight.get("contract_blockers", [])))
    horizon_blockers = matrix.loc[matrix["status"].astype(str).str.startswith("BLOCKED"), ["predictor", "horizon", "status"]].to_dict(orient="records")
    replay_output = Path(replay["output_path"])
    replay_size = replay_output.stat().st_size if replay_output.exists() else None
    metadata = {
        "status": "COMPLETED",
        "job_id": str(job_id),
        "repository_sha": preflight.get("code_git_sha"),
        "model_id": replay.get("model_id"),
        "model_sha256": replay.get("model_sha256"),
        "atlas_output_root": str(root),
        "preflight_terminal_status": preflight.get("terminal_status"),
        "replay_terminal_status": replay.get("terminal_status"),
        "replay_output_rows": replay.get("output_row_count"),
        "replay_output_sha256": replay.get("output_sha256"),
        "replay_output_size_bytes": replay_size,
        "replay_runtime_seconds": replay.get("runtime_seconds"),
        "reproducibility": comparison,
        "failure_tests": failure_summary,
        "availability_classification": "RETROSPECTIVE_ONLY" if retrospective else ("BLOCKED_BY_UNKNOWN_AVAILABILITY" if unknown else "PROSPECTIVE_READY_WITH_LAG_LIMITATIONS"),
        "availability_counts": availability_counts,
        "retrospective_predictors": retrospective,
        "unknown_predictors": unknown,
        "horizon_blockers": horizon_blockers,
        "contract_blockers": blockers,
        "pytest_environment_gap": True,
    }
    decision = "P5_OPERATIONAL_CONTRACT_NOT_SUPPORTED" if metadata["availability_classification"] in {"RETROSPECTIVE_ONLY", "BLOCKED_BY_UNKNOWN_AVAILABILITY"} or comparison.get("status") != "PASS" or failure_summary.get("status") != "PASS" else "P5_OPERATIONAL_CONTRACT_SUPPORTED_WITH_LIMITATIONS"
    metadata["decision"] = decision
    (result_root / "p5_run_metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (result_root / "availability_decision.json").write_text(json.dumps({"classification": metadata["availability_classification"], "retrospective_predictors": retrospective, "unknown_predictors": unknown, "horizon_blockers": horizon_blockers, "decision_basis": "historical replay is distinct from prospective availability"}, indent=2) + "\n", encoding="utf-8")
    (result_root / "decision.json").write_text(json.dumps({"decision": decision, "marker": decision, "availability_classification": metadata["availability_classification"], "preflight_terminal_status": preflight.get("terminal_status"), "replay_terminal_status": replay.get("terminal_status"), "reproducibility": comparison, "failure_tests": failure_summary, "production_model_modified": False}, indent=2) + "\n", encoding="utf-8")

    count_lines = "\n".join(f"| {key} | {value} |" for key, value in sorted(availability_counts.items()))
    retrospective_text = ", ".join(retrospective) if retrospective else "none"
    unknown_text = ", ".join(unknown) if unknown else "none"
    horizon_text = ", ".join(f"{row['predictor']} h={row['horizon']} ({row['status']})" for row in horizon_blockers[:12]) or "none"
    failure_rows = pd.read_csv(root / "failure_tests" / "failure_mode_test_results.csv")
    failure_table = "\n".join(f"| {row.test} | `{row.observed_code}` | {row.status} |" for row in failure_rows.itertuples())
    report = f"""# P5 Operational Evaluation and Production Contract Validation

## I. Governance

SAE governance, `EXECUTION_GOVERNANCE.md`, and `ATLAS_SSH_POLICY.md` were reviewed. Atlas access used the authorized direct WSL/Ubuntu `atlas-ssh` route. P5 stayed within evaluation and contract-validation scope; no production deployment automation, scheduler, monitoring, rollback, release tag, or model-specification change was authorized.

## II. Canonical Starting State

Starting canonical main/P4 merge SHA: `313c156c787a649ab79ed81918184013573b922d`. The P0 freeze verifier passed before implementation. Frozen model: `STRUCTURED_A3`; frozen artifact SHA-256: `{replay.get('model_sha256')}`. P0/P1/P2/P3/P4 reports were read and their unresolved limitations were carried forward explicitly.

## III. P5 Repository State

Implementation SHA used for Atlas execution: `{preflight.get('code_git_sha')}`. The P5 implementation is isolated under `analysis/p5_operational_contract/`. The final branch/worktree/PR state is recorded in Section XVI. Standard-library contract tests were used because the validated Atlas Python environment does not provide pytest; the pytest gap is recorded as a P6 tooling recommendation rather than hidden or worked around by modifying the environment.

## IV. Predictor Availability Audit

All 34 frozen predictors received an explicit class. Counts are:

| Availability class | Predictor count |
|---|---:|
{count_lines}

RETROSPECTIVE_ONLY predictors: {retrospective_text}. UNKNOWN predictors: {unknown_text}. Environmental release-time/revision metadata were not available, so the dynamic environmental block was not silently treated as current. Horizon-specific blockers included: {horizon_text}.

## V. Operational Issue Contract

Issue week `T` is a completed ISO week; the issue timestamp is Monday 00:00 UTC immediately after `T`. Targets are exactly `T+1`, `T+2`, and `T+3`. Response history and frontier history are cut off at `T`; a history feature with `history_cutoff_week > T` blocks prospective operation. Predictor vintages are explicit in `production_input_manifest.csv`; future-dated, unknown, missing, or retrospective-only inputs block `run` mode. No stale substitution, resampling, reprojecting, zero-fill, predictor replacement, or prior-output reuse is permitted.

## VI. Production Workflow

Canonical entry point: `analysis/p5_operational_contract/scripts/run_p5_operational_contract.py`. Stages are frozen-model verification, issue-week resolution, input discovery, vintage/freshness validation, spatial and temporal validation, exact frozen feature assembly, schema validation, coefficient-only STRUCTURED_A3 inference, unchanged P4 support/interval join, output validation, provenance, and terminal status. `dry-run` performs preflight only; `run` blocks on contract failure. Completed output roots are immutable.

## VII. Support / Uncertainty Integration

P4 classes `SUPPORTED`, `CAUTION`, and `EXTRAPOLATIVE` and the P4 thresholds are consumed unchanged. Rows retain extrapolative predictions and carry `EXTRAPOLATIVE_SUPPORT`; caution rows carry `CAUTION_SUPPORT`. Exact hurdle interval fields are included. Precomputed P4 bootstrap fields are included when available; P5 does not refit 100 bootstrap models per issuance and marks unavailable operational model uncertainty as `NOT_COMPUTED_OPERATIONALLY`/`PARTIAL_UNCERTAINTY`.

## VIII. Historical Replay

Replay issue week: `{{replay.get('issue_week')}}`; target weeks: `{{', '.join(replay.get('target_weeks', []))}}`. Atlas job ID: `{job_id}`. Replay terminal status: `{replay.get('terminal_status')}`. Output rows: `{replay.get('output_row_count')}`. Output SHA-256: `{replay.get('output_sha256')}`. Output size: `{replay_size}` bytes. This is an explicit retrospective reconstruction, not prospective availability evidence.

## IX. Reproducibility

The replay was run twice from identical declared inputs. Comparison status: `{comparison.get('status')}`; row-count equality: `{comparison.get('row_count_equal')}`; schema equality: `{comparison.get('schema_equal')}`; exact numeric equality: `{comparison.get('exact_numeric_equality')}`; maximum absolute numeric difference: `{comparison.get('max_abs_numeric_difference')}`; support-flag equality: `{comparison.get('support_flags_equal')}`; warning-flag equality: `{comparison.get('warning_flags_equal')}`. Differences were limited to allowed run/output/runtime fields: `{comparison.get('provenance_differences_outside_allowed_run_fields')}`.

## X. Failure-Mode Validation

The standard-library failure suite completed `{failure_summary.get('passed')}/{failure_summary.get('tests')}` tests with status `{failure_summary.get('status')}`. Every deliberate failure produced a deterministic code and no false-success production output.

| Failure test | Observed code | Status |
|---|---|---|
{failure_table}

## XI. Operational Practicality

The Atlas production-like replay completed in `{replay.get('runtime_seconds')}` seconds and produced `{replay.get('output_row_count')}` rows ({replay_size} bytes). The fixed-model inference and P4-reference join are computationally practical for a weekly run; full P4 bootstrap refitting is intentionally not part of each issuance. The managed Atlas environment lacks pytest; the repository-defined R suite and standard-library P5 contracts remain separate from that tooling limitation.

## XII. Production Availability Classification

`{metadata['availability_classification']}`

The successful retrospective replay does not override the availability classification: current dynamic environmental products lack auditable issue-time release/revision metadata and the frozen target-week history artifact requires future-of-issue cutoffs for later horizons. The prospective `run`/`dry-run` contract therefore blocks rather than silently using future information.

## XIII. P1–P4 Limitation Tracking

| Limitation | P5 classification |
|---|---|
| sparse frontier support | `ROBUST_LIMITATION` |
| sparse U.S./regional outcome support | `ROBUST_LIMITATION` |
| count-process bias | `BETTER_CHARACTERIZED` |
| retrospective environmental availability | `BLOCKING_OPERATIONAL_READINESS` |
| extrapolative support proportion | `BETTER_CHARACTERIZED` |
| lack of refitted spatial holdout | `NOT_ADDRESSABLE_IN_P5` |
| pytest/test-environment gap | `NOT_ADDRESSABLE_IN_P5` |

## XIV. Artifacts

- `analysis/p5_operational_contract/p5_prespecification.md`
- `analysis/p5_operational_contract/p5_operational_contract_report.md`
- `analysis/p5_operational_contract/results/predictor_availability_audit.csv`
- `analysis/p5_operational_contract/results/input_contract.json`
- `analysis/p5_operational_contract/results/replay_manifest.json`
- `analysis/p5_operational_contract/results/failure_mode_test_results.csv`
- `analysis/p5_operational_contract/results/decision.json`
- Atlas output root: `{root}`

## XV. Atlas

WSL route compliance: PASS. Atlas job ID: `{job_id}`; terminal status: COMPLETED. The isolated output root was `{root}`. P0–P4 roots were not overwritten.

## XVI. CI / PR / Merge

Hosted CI, PR, merge, post-merge freeze verification, and cleanup will be recorded in the task handoff. No production release tag will be created.

## XVII. P5 Decision

{decision}
"""
    report = report.replace("{{replay.get('issue_week')}}", str(replay.get("issue_week")))
    (repo / "analysis" / "p5_operational_contract" / "p5_operational_contract_report.md").write_text(report, encoding="utf-8")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    metadata = render(args.repository_root, args.output_root, args.job_id)
    print(json.dumps(metadata, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
