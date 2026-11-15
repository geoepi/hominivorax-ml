"""Finalize the one-shot A6-VIF status after its model process exits."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    if os.name == "posix":
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def latest_progress(root: Path) -> dict[str, Any] | None:
    path = root / "logs/progress.jsonl"
    if not path.exists():
        return None
    last = None
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                last = json.loads(line)
    return last


def finalize(root: Path, exit_code: int, budget_exceeded: bool, reason: str | None, durable_report: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    run_status_path = root / "results/run_status.json"
    decision_path = root / "results/a6_vif_gate_decision.json"
    existing = json.loads(decision_path.read_text(encoding="utf-8")) if decision_path.exists() else {}
    terminal_states = {
        "A6_VIF_GATE_SUPPORTED",
        "A6_VIF_GATE_SUPPORTED_WITH_LIMITATIONS",
        "A6_VIF_GATE_NOT_SUPPORTED",
    }
    if existing.get("status") not in terminal_states:
        last = latest_progress(root)
        state = "INCOMPLETE_BUDGET_EXCEEDED" if budget_exceeded else "FAILED"
        for status_path in root.rglob("status.json"):
            try:
                status = json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if status.get("status") == "RUNNING":
                status.update({"status": state, "finalized_utc": utc_now(), "finalizer_reason": reason or f"runner exit code {exit_code}"})
                atomic_json(status_path, status)
        decision = {
            **existing,
            "status": "A6_VIF_GATE_NOT_SUPPORTED",
            "fold": 3,
            "seed": 31415,
            "failure_classification": state,
            "reason": reason or ("A6-VIF runner exited before writing a completed gate decision" if exit_code != 0 else "A6-VIF did not produce a successful gate decision"),
            "runner_exit_code": int(exit_code),
            "budget_exceeded": bool(budget_exceeded),
            "last_progress": last,
            "completed_stage_a_estimates": [str(path) for path in root.rglob("stage_a_estimate.json") if path.with_name("completion.json").exists()],
            "stage_b_completed": any(path.name == "completion.json" and path.parent.parent.name == "seed_31415" for path in root.rglob("completion.json")),
            "finalized_utc": utc_now(),
        }
        atomic_json(decision_path, decision)
        report = (
            "# A6-VIF bounded qualification gate\n\n"
            "**Gate decision:** `A6_VIF_GATE_NOT_SUPPORTED`\n\n"
            f"- Failure classification: `{state}`.\n"
            f"- Reason: {decision['reason']}\n"
            f"- Runner exit code: {exit_code}.\n"
            f"- Last recorded stage: `{last.get('stage') if last else 'NOT_RECORDED'}` / `{last.get('event') if last else 'NOT_RECORDED'}`.\n"
            f"- Completed Stage A estimates: {len(decision['completed_stage_a_estimates'])}.\n"
            f"- Stage B completed: {str(decision['stage_b_completed']).lower()}.\n\n"
            "No retry or additional model unit was launched. Any valid atomically completed Stage A estimates remain available under this run root.\n"
        )
        report_path = root / "results/a6_vif_gate_report.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
        if durable_report is not None:
            durable_report.parent.mkdir(parents=True, exist_ok=True)
            durable_report.write_text(report, encoding="utf-8")
    else:
        decision = existing

    one_shot_path = root / "provenance/one_shot_execution_started.json"
    if one_shot_path.exists():
        one_shot = json.loads(one_shot_path.read_text(encoding="utf-8"))
        if one_shot.get("status") == "STARTED":
            one_shot.update({
                "status": "COMPLETED" if exit_code == 0 and not budget_exceeded else "INCOMPLETE",
                "gate_status": decision.get("status"),
                "completed_utc": utc_now(),
                "runner_exit_code": int(exit_code),
                "budget_exceeded": bool(budget_exceeded),
            })
            atomic_json(one_shot_path, one_shot)

    run_status = {
        "status": decision.get("status", "A6_VIF_GATE_NOT_SUPPORTED"),
        "runner_exit_code": int(exit_code),
        "budget_exceeded": bool(budget_exceeded),
        "reason": reason,
        "last_progress": latest_progress(root),
        "finalized_utc": utc_now(),
    }
    atomic_json(run_status_path, run_status)

    manifest_path = root / "provenance/final_artifact_checksums.json"
    files = [
        {"path": str(path.relative_to(root)), "size_bytes": int(path.stat().st_size), "sha256": sha256_file(path)}
        for path in sorted(root.rglob("*"))
        if path.is_file() and path != manifest_path and not path.name.endswith(".tmp")
    ]
    atomic_json(manifest_path, {
        "status": "FINALIZED",
        "gate_status": decision.get("status"),
        "runner_exit_code": int(exit_code),
        "budget_exceeded": bool(budget_exceeded),
        "files": files,
        "created_utc": utc_now(),
    })
    return {"status": decision.get("status"), "exit_code": int(exit_code), "budget_exceeded": bool(budget_exceeded), "manifest": str(manifest_path)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--budget-exceeded", action="store_true")
    parser.add_argument("--reason")
    parser.add_argument("--durable-report", type=Path)
    args = parser.parse_args()
    print(json.dumps(finalize(args.output_root, args.exit_code, args.budget_exceeded, args.reason, args.durable_report), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
