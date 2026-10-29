#!/usr/bin/env python3
"""Verify the immutable Structured A3 production-candidate freeze.

This verifier checks the tracked freeze contract, artifact hashes, predictor
metadata, provenance cross-references, and a small coefficient-only inference
fixture. It never loads protected production data and never fits a model.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "config" / "production_model_freeze.json"
EXPECTED_MODEL_ID = "STRUCTURED_A3"
EXPECTED_PREDICTOR_COUNT = 34
EXPECTED_THETA = 0.7018903965556372
EXPECTED_PENALTY = 0.01
TOLERANCE = 1e-12


class FreezeVerificationError(RuntimeError):
    """A freeze contract has been violated."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FreezeVerificationError(f"cannot parse JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FreezeVerificationError(f"JSON document is not an object: {path}")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FreezeVerificationError(message)


def is_excluded_predictor(name: str) -> bool:
    lower = name.lower()
    return "flight" in lower or lower == "sit" or lower.startswith("sit_") or "_sit_" in lower or lower.endswith("_sit")


def repo_path(repo_root: Path, relative: str) -> Path:
    path = Path(relative)
    return path if path.is_absolute() else repo_root / path


def git_value(repo_root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-c", "safe.directory=*", *args],
            cwd=repo_root,
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise FreezeVerificationError(f"Git provenance check failed: {exc}") from exc


def check_source_revision(manifest: dict[str, Any], repo_root: Path) -> None:
    identity = manifest["identity"]
    source = manifest["source_revision"]
    base_sha = str(identity["repository_sha_at_freeze_branch_base"])
    require(source["repository_sha_at_freeze_branch_base"] == base_sha, "repository base SHA is inconsistent")
    current_sha = git_value(repo_root, "rev-parse", "HEAD")
    try:
        subprocess.run(
            ["git", "-c", "safe.directory=*", "merge-base", "--is-ancestor", base_sha, current_sha],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise FreezeVerificationError(
            f"current repository HEAD {current_sha} is not descended from freeze base SHA {base_sha}"
        ) from exc


def check_artifacts(manifest: dict[str, Any], repo_root: Path) -> dict[str, Path]:
    artifacts = manifest.get("frozen_artifacts")
    require(isinstance(artifacts, list) and artifacts, "frozen_artifacts must be a non-empty list")
    paths: dict[str, Path] = {}
    for artifact in artifacts:
        require(isinstance(artifact, dict), "each frozen artifact entry must be an object")
        artifact_id = str(artifact.get("id", ""))
        relative = artifact.get("path")
        expected_hash = str(artifact.get("sha256", ""))
        require(artifact_id and isinstance(relative, str), "artifact id and path are required")
        require(len(expected_hash) == 64, f"artifact {artifact_id} has no SHA-256 hash")
        path = repo_path(repo_root, relative)
        require(path.is_file(), f"required artifact is missing: {relative}")
        actual_hash = sha256_file(path)
        require(actual_hash == expected_hash, f"artifact hash mismatch for {relative}: {actual_hash} != {expected_hash}")
        if artifact.get("size_bytes") is not None:
            require(path.stat().st_size == int(artifact["size_bytes"]), f"artifact size mismatch for {relative}")
        paths[artifact_id] = path
    return paths


def predictor_names(manifest: dict[str, Any]) -> list[str]:
    entries = manifest["predictor_specification"]["ordered_predictors"]
    require(len(entries) == EXPECTED_PREDICTOR_COUNT, "freeze predictor count is not 34")
    names = []
    for entry in entries:
        require(isinstance(entry, dict), "predictor entries must be objects")
        for field in ("name", "source_layer", "transformation", "lag", "scaling", "missing_data_treatment"):
            require(entry.get(field) not in (None, ""), f"predictor entry is missing {field}")
        names.append(str(entry["name"]))
    require(len(names) == len(set(names)), "freeze predictor names are not unique")
    require(not any(is_excluded_predictor(name) for name in names), "excluded flight/SIT feature was added to the freeze")
    return names


def check_predictor_csv(path: Path, names: list[str]) -> None:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    selected = [row["predictor"] for row in rows if row.get("included_in_A3") == "YES"]
    require(selected == names, "docs/current/predictors.csv does not match the frozen predictor order")
    require(not any(is_excluded_predictor(name) for name in selected), "predictor CSV requires excluded flight/SIT inputs")


def check_model_metadata(
    manifest: dict[str, Any],
    model: dict[str, Any],
    eval_manifest: dict[str, Any],
    final_manifest: dict[str, Any],
    feature_manifest: dict[str, Any],
    names: list[str],
) -> None:
    identity = manifest["identity"]
    spec = manifest["model_specification"]
    scientific = manifest["scientific_specification"]
    require(model.get("model") == EXPECTED_MODEL_ID, "stored model identifier is not STRUCTURED_A3")
    require(model.get("feature_count") == EXPECTED_PREDICTOR_COUNT, "stored model feature count is not 34")
    require(model.get("feature_order") == names, "stored model feature order differs from freeze")
    require(model.get("preprocessing", {}).get("feature_names") == names, "stored preprocessing schema differs from freeze")
    require(len(model.get("occurrence_coefficients", [])) == EXPECTED_PREDICTOR_COUNT + 1, "occurrence coefficient vector has the wrong length")
    require(len(model.get("count_coefficients", [])) == EXPECTED_PREDICTOR_COUNT + 1, "positive-count coefficient vector has the wrong length")
    require(model.get("objective") == spec["objective"], "stored objective differs from freeze")
    require(float(model.get("penalty")) == EXPECTED_PENALTY == float(spec["regularization_penalty"]), "stored penalty differs from freeze")
    require(bool(model.get("theta_fixed")) is True, "stored theta is not marked fixed")
    require(float(model.get("theta")) == EXPECTED_THETA == float(spec["theta"]), "stored theta differs from freeze")
    require(model.get("training_period") == {
        "start": scientific["fitting_horizon"]["start_week"],
        "end": scientific["fitting_horizon"]["end_week"],
        "week_count": scientific["fitting_horizon"]["week_count"],
    }, "stored training period differs from freeze")
    fit_info = model.get("fit_info", {})
    require(bool(fit_info.get("occurrence_success")) and bool(fit_info.get("count_success")), "stored fit is not marked converged")
    require(int(fit_info.get("training_rows")) == scientific["training_rows"], "stored training row count differs from freeze")
    require(int(fit_info.get("training_positive_rows")) == scientific["training_positive_rows"], "stored positive row count differs from freeze")
    require(model.get("software_sha") == manifest["source_revision"]["historical_model_generation_sha_recorded_in_artifact"], "model software SHA is inconsistent with source revision record")

    preprocessing = model["preprocessing"]
    freeze_entries = manifest["predictor_specification"]["ordered_predictors"]
    expected_unscaled = [index for index, entry in enumerate(freeze_entries) if str(entry["scaling"]).startswith("unscaled")]
    expected_scaled = [index for index in range(EXPECTED_PREDICTOR_COUNT) if index not in expected_unscaled]
    require(preprocessing.get("scaled_feature_indices") == expected_scaled, "stored scaled predictor indices differ from freeze")
    require(preprocessing.get("unscaled_feature_indices") == expected_unscaled, "stored unscaled predictor indices differ from freeze")

    eval_model = eval_manifest.get("model", {})
    require(eval_manifest.get("manifest_status") == "FROZEN_BEFORE_EVALUATION_OUTCOMES", "evaluation manifest is not frozen before outcomes")
    require(eval_model.get("id") == EXPECTED_MODEL_ID, "evaluation manifest model identifier differs")
    require(eval_model.get("predictor_count") == EXPECTED_PREDICTOR_COUNT, "evaluation manifest predictor count differs")
    require(eval_model.get("predictor_order") == names, "evaluation manifest predictor order differs")
    require(float(eval_model.get("theta")) == EXPECTED_THETA and float(eval_model.get("penalty")) == EXPECTED_PENALTY, "evaluation manifest theta/penalty differs")
    require(eval_model.get("objective") == spec["objective"], "evaluation manifest objective differs")
    require(eval_manifest.get("domain", {}).get("node_count") == scientific["node_count"], "evaluation manifest domain size differs")
    require(eval_manifest.get("development_protocol", {}).get("training_period", {}).get("start_week") == scientific["fitting_horizon"]["start_week"], "evaluation training start differs")
    require(eval_manifest.get("development_protocol", {}).get("training_period", {}).get("end_week") == scientific["fitting_horizon"]["end_week"], "evaluation training end differs")

    require(final_manifest.get("status") == "complete", "final comparison manifest is not complete")
    decision = final_manifest.get("decision", {})
    require(final_manifest.get("final_structured_specification") == EXPECTED_MODEL_ID or decision.get("final_structured_specification") == "STRUCTURED A3", "final comparison does not identify Structured A3")
    require(final_manifest.get("a3_predictor_count") == EXPECTED_PREDICTOR_COUNT, "final comparison predictor count differs")
    require(decision.get("feature_selection_reopened") is False, "final comparison reopened feature selection")
    require(decision.get("response_changed") is False, "final comparison changed the response")
    require(decision.get("penalty_changed") is False, "final comparison changed the penalty")
    require(decision.get("theta_reestimated") is False, "final comparison re-estimated theta")
    require(decision.get("terminal_later_outcomes_used") is False, "final comparison used later outcomes")
    require(feature_manifest.get("added_features") == names[-4:], "A3 feature provenance does not match the frozen final predictors")


def logistic(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


def infer(model: dict[str, Any], values: list[float]) -> dict[str, float]:
    preprocessing = model["preprocessing"]
    mean = [float(value) for value in preprocessing["training_mean"]]
    sd = [float(value) for value in preprocessing["training_sd"]]
    require(len(values) == len(mean) == EXPECTED_PREDICTOR_COUNT, "inference row does not match the frozen predictor count")
    require(all(math.isfinite(value) for value in values), "inference row contains non-finite values")
    standardized = [(value - center) / scale for value, center, scale in zip(values, mean, sd)]
    occurrence = [float(value) for value in model["occurrence_coefficients"]]
    count = [float(value) for value in model["count_coefficients"]]
    occurrence_eta = max(-40.0, min(40.0, occurrence[0] + sum(value * beta for value, beta in zip(standardized, occurrence[1:]))))
    count_eta = max(-20.0, min(20.0, count[0] + sum(value * beta for value, beta in zip(standardized, count[1:]))))
    probability = logistic(occurrence_eta)
    mu = math.exp(count_eta)
    theta = float(model["theta"])
    log_p_zero = theta * (math.log(theta) - math.log(theta + mu))
    conditional = mu / max(-math.expm1(log_p_zero), 1e-12)
    return {
        "p_occurrence": probability,
        "conditional_count_mean": conditional,
        "expected_count": probability * conditional,
    }


def check_fixture(path: Path, model: dict[str, Any], names: list[str]) -> None:
    fixture = load_json(path)
    require(fixture.get("matrix_type") == "transformed_model_matrix", "inference fixture matrix type is not explicit")
    require(fixture.get("predictor_order") == names, "inference fixture predictor schema differs from freeze")
    rows = fixture.get("rows")
    require(isinstance(rows, list) and rows, "inference fixture has no rows")
    first_pass = []
    second_pass = []
    for row in rows:
        require(isinstance(row, dict) and row.get("id"), "inference fixture row is malformed")
        values = row.get("values")
        require(isinstance(values, list), f"inference fixture row {row['id']} has no values")
        result = infer(model, [float(value) for value in values])
        first_pass.append(result)
        second_pass.append(infer(model, [float(value) for value in values]))
        expected = row.get("expected")
        require(isinstance(expected, dict), f"inference fixture row {row['id']} has no expected answer")
        for key, actual in result.items():
            require(abs(actual - float(expected[key])) <= TOLERANCE, f"known-answer inference mismatch for {row['id']}:{key}: {actual} != {expected[key]}")
    require(first_pass == second_pass, "repeated frozen-model inference was not deterministic")


def verify(manifest_path: Path = DEFAULT_MANIFEST, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    required_top_level = {
        "manifest_version", "manifest_status", "identity", "scientific_specification",
        "predictor_specification", "model_specification", "training_data_provenance",
        "source_revision", "frozen_artifacts", "software_environment",
        "immutability_contract", "qualification_boundary", "verification",
    }
    require(required_top_level.issubset(manifest), "freeze manifest is missing required top-level fields")
    require(manifest["identity"].get("model_id") == EXPECTED_MODEL_ID, "repository/model identifier is not recognized")
    require(manifest["identity"].get("model_role") == "primary", "freeze role is not primary")
    require(manifest["identity"].get("freeze_date") == "2026-10-06", "freeze date is inconsistent with the historical A3 record")
    require(manifest["scientific_specification"].get("evaluation_period_used_for_fit") is False, "evaluation responses were used for fitting")
    require(manifest["qualification_boundary"].get("p1_p7_must_not_silently_modify_p0") is True, "qualification immutability boundary is missing")
    require(manifest["qualification_boundary"].get("flight_path_predictors_included") is False, "flight-path exclusion is missing")
    require(manifest["qualification_boundary"].get("sit_predictors_included") is False, "SIT exclusion is missing")
    check_source_revision(manifest, repo_root)
    artifact_paths = check_artifacts(manifest, repo_root)
    names = predictor_names(manifest)
    check_predictor_csv(artifact_paths["predictor_schema_manifest"], names)
    model = load_json(artifact_paths["frozen_model_metadata_and_coefficients"])
    eval_manifest = load_json(artifact_paths["frozen_evaluation_manifest"])
    final_manifest = load_json(artifact_paths["structured_a3_final_manifest"])
    feature_manifest = load_json(artifact_paths["a3_feature_manifest"])
    check_model_metadata(manifest, model, eval_manifest, final_manifest, feature_manifest, names)
    check_fixture(artifact_paths["known_answer_inference_fixture"], model, names)
    for reference in (manifest["software_environment"]["environment_reference"], manifest["software_environment"]["runtime_bootstrap"], manifest["software_environment"]["deployment_configuration_reference"]):
        require(repo_path(repo_root, reference).exists(), f"environment reference is missing: {reference}")
    return {
        "manifest": "PASS",
        "artifacts": "PASS",
        "predictor_schema": "PASS",
        "model_metadata": "PASS",
        "known_answer_inference": "PASS",
        "deterministic_inference": "PASS",
        "trains_model": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = verify(args.manifest.resolve(), args.repo_root.resolve())
    except FreezeVerificationError as exc:
        print(f"PRODUCTION_MODEL_FREEZE_FAILED: {exc}")
        return 1
    print("PRODUCTION_MODEL_FREEZE_VERIFIED")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
