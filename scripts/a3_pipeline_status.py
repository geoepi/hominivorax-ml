#!/usr/bin/env python3
"""Summarize an Atlas A3 submission manifest and optional SLURM state."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--log-root", default="/project/disease_ecology/STGNN-output/logs")
    args = parser.parse_args()
    path = Path(args.log_root) / args.run_id / "submission_manifest.json"
    if not path.exists():
        raise SystemExit(f"run manifest not found: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    print(f"run_id: {manifest.get('run_id')}")
    print(f"mode: {manifest.get('mode')}")
    print(f"repository_sha: {manifest.get('repository_sha')}")
    for stage, record in manifest.get("stages", {}).items():
        job_id = record.get("job_id", "")
        state = "unknown"
        if job_id and job_id not in {"LOCAL", "NOT_SUBMITTED"}:
            try:
                state = subprocess.check_output(["squeue", "-h", "-j", str(job_id), "-o", "%T"], text=True).strip() or "not-in-squeue"
            except (OSError, subprocess.CalledProcessError):
                state = "slurm-state-unavailable"
        print(f"stage={stage} job_id={job_id} status={record.get('status')} slurm_state={state} output_status={record.get('output_manifest_sha') or 'pending'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
