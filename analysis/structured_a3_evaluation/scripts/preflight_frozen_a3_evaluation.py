#!/usr/bin/env python3
"""Outcome-blind preflight for the frozen STRUCTURED A3 evaluation.

This command verifies the immutable manifest and the presence of required
authoritative artifacts without loading response arrays or generating metrics.
It is safe to run before an evaluation refresh is authorized.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
EVAL_ROOT = REPO_ROOT / "analysis" / "structured_a3_evaluation"
MANIFEST = EVAL_ROOT / "results" / "frozen_a3_evaluation_manifest.json"
CHECKSUM = EVAL_ROOT / "results" / "frozen_a3_evaluation_manifest.json.sha256"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-c", f"safe.directory={REPO_ROOT.as_posix()}", *args],
            cwd=REPO_ROOT,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path("D:/project/disease_ecology"))
    parser.add_argument("--write-provenance", action="store_true")
    args = parser.parse_args()

    if not MANIFEST.exists() or not CHECKSUM.exists():
        raise SystemExit("STOP: immutable frozen A3 manifest or checksum is missing")
    actual = sha256(MANIFEST)
    recorded = CHECKSUM.read_text(encoding="utf-8").split()[0]
    if actual != recorded:
        raise SystemExit("STOP: frozen A3 manifest checksum mismatch")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("manifest_status") != "FROZEN_BEFORE_EVALUATION_OUTCOMES":
        raise SystemExit("STOP: manifest is not marked frozen before evaluation outcomes")
    if manifest["model"]["predictor_count"] != 34 or len(manifest["model"]["predictor_order"]) != 34:
        raise SystemExit("STOP: frozen A3 predictor contract is incomplete")
    if float(manifest["model"]["penalty"]) != 0.01 or float(manifest["model"]["theta"]) != 0.7018903965556372:
        raise SystemExit("STOP: frozen A3 penalty/theta contract changed")

    project_root = args.project_root
    required = {
        "revised_model_data": project_root / "STGNN-output" / "revised_model_data",
        "causal_front_features": project_root / "STGNN-output" / "v2_model" / "front_features" / "causal_front_features.parquet",
        "anthropogenic_static_features": project_root / "STGNN-output" / "predictor_augmentation" / "static" / "road_night_node_features.parquet",
        "soil_static_features": project_root / "STGNN-output" / "soil_feature_screening_resumed_s1" / "soil_node_features.parquet",
    }
    availability = {name: {"path": str(path), "exists": path.exists()} for name, path in required.items()}
    missing = [name for name, item in availability.items() if not item["exists"]]
    result = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "READY_FOR_OUTCOME_BLIND_DATA_AUDIT" if not missing else "STOP_REQUIRED_FROZEN_INPUTS_UNAVAILABLE",
        "manifest_sha256": actual,
        "git_head": git("rev-parse", "HEAD"),
        "project_root": str(project_root),
        "required_artifacts": availability,
        "missing_artifacts": missing,
        "response_values_loaded": False,
        "metrics_generated": False,
        "prospective_claim_allowed": False,
    }
    if args.write_provenance:
        write_json(EVAL_ROOT / "results" / "data_refresh_provenance.json", result)
    print(json.dumps(result, indent=2))
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
