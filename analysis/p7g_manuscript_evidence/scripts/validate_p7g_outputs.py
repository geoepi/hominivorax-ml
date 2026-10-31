#!/usr/bin/env python3
"""Fail-closed validation for compact P7G outputs."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"P7G_VALIDATION_FAILED: {message}")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    result = root / "results"
    required = [
        "configuration.json", "decision.json", "source_hash_manifest.json",
        "predictor_analysis_metadata.json", "early_warning_topk.csv",
        "early_warning_trajectory.csv", "first_detection_event_rankings.csv",
        "predictor_dependence_pairs.csv", "predictor_dependence_summary.csv",
        "predictor_standardized_associations.csv", "spatial_dependence.csv",
        "spatial_shell_dependence.csv", "temporal_dependence.csv",
        "support_class_proportions.csv", "support_horizon_calibration_metrics.csv",
        "support_horizon_reliability.csv", "support_horizon_bootstrap_ci.csv",
    ]
    for name in required:
        require((result / name).exists(), f"missing {name}")
    config = json.loads((result / "configuration.json").read_text(encoding="utf-8"))
    decision = json.loads((result / "decision.json").read_text(encoding="utf-8"))
    metadata = json.loads((result / "predictor_analysis_metadata.json").read_text(encoding="utf-8"))
    require(config["model_id"] == "STRUCTURED_A3", "model id changed")
    require(config["p0_model_sha256"] == "8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e", "model hash changed")
    require(config["no_model_fitting"] is True and config["p4_bootstrap_reused"] is False, "analysis contract flags changed")
    require(decision["decision"] == "P7G_MANUSCRIPT_EVIDENCE_COMPLETE_WITH_LIMITATIONS", "unexpected decision")
    require(metadata["predictor_count"] == 34, "predictor count changed")
    require(metadata["p4_coefficient_bootstrap_available"] is False, "unexpected P4 bootstrap availability")
    dep = rows(result / "predictor_dependence_pairs.csv")
    require(len(dep) == 561, f"expected 561 predictor pairs, got {len(dep)}")
    assoc = rows(result / "predictor_standardized_associations.csv")
    require(len(assoc) == 68, f"expected 68 component associations, got {len(assoc)}")
    spatial = rows(result / "spatial_shell_dependence.csv")
    require(len(spatial) == 72, f"expected 72 spatial shell rows, got {len(spatial)}")
    require({int(r["horizon"]) for r in spatial} == {1, 2, 3}, "spatial horizon coverage incomplete")
    require({int(r["shell_order"]) for r in spatial} == {1, 2, 3, 4}, "spatial shell coverage incomplete")
    temporal = rows(result / "temporal_dependence.csv")
    require(len(temporal) == 72, f"expected 72 temporal rows, got {len(temporal)}")
    support = rows(result / "support_horizon_calibration_metrics.csv")
    require(len(support) == 9, f"expected 9 support-by-horizon rows, got {len(support)}")
    require({r["support_class"] for r in support} == {"SUPPORTED", "CAUTION", "EXTRAPOLATIVE"}, "support classes incomplete")
    reliability = rows(result / "support_horizon_reliability.csv")
    require(len(reliability) == 90, f"expected 90 reliability rows, got {len(reliability)}")
    ci = rows(result / "support_horizon_bootstrap_ci.csv")
    require(all(int(r["bootstrap_replicates"]) == 199 for r in ci), "bootstrap replicate count changed")
    hashes = json.loads((result / "source_hash_manifest.json").read_text(encoding="utf-8"))
    require(hashes["p2_archive"]["sha256"] == config["p2_archive_sha256"], "P2 source hash mismatch")
    require(hashes["p4_support"]["sha256"] == config["p4_support_sha256"], "P4 source hash mismatch")
    print(json.dumps({"status": "P7G_OUTPUTS_VALIDATED", "required_files": len(required), "predictor_pairs": len(dep), "support_rows": len(support), "no_model_fitting": True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
