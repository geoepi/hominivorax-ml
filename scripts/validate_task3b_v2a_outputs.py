#!/usr/bin/env python3
"""Validate persisted Task 3B V2-A artifacts and their provenance checksums."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


OUTPUT = Path("/project/disease_ecology/STGNN-output/v2_model")
SOURCE = Path("/project/disease_ecology/NWScrewworm/data/processed_data/case_detections/combined_clean_obs_2027-07-31.csv")
SOURCE_SHA = "a3d55f3ddf867087b578df803920bf59c6c303fa695e3218a5f3463e596d497e"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    required = [
        "front_features/causal_front_features.parquet",
        "front_features/latitude_ablation_features.parquet",
        "validation/validation_predictions.parquet",
        "metrics/selected_penalty_metrics.csv",
        "metrics/v1_reproduction.csv",
        "metrics/task3b_decisions.json",
        "manifests/task3b_v2a_manifest.json",
        "manifests/task3b_v2a_checksums.csv",
    ]
    for relative in required:
        assert (OUTPUT / relative).is_file(), relative

    manifest = json.loads((OUTPUT / "manifests/task3b_v2a_manifest.json").read_text())
    decisions = json.loads((OUTPUT / "metrics/task3b_decisions.json").read_text())
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    assert manifest["git_sha"] == head, (manifest["git_sha"], head)
    assert manifest["branch"] == "feature/v2-front-hurdle"
    assert manifest["source_observation_sha256"] == SOURCE_SHA
    assert manifest["predictive_models_outside_v2a_fitted"] is False
    assert manifest["neural_models_fitted"] is False
    assert manifest["optimizer_settings"]["method"] == "L-BFGS-B"
    assert manifest["optimizer_settings"]["maxiter"] == 2000
    assert decisions["v2a_decision"] in {
        "V2-A ADVANCES",
        "V2-A IMPROVES PERSISTENCE ONLY",
        "V2-A HOLD / AMBIGUOUS",
        "V2-A DOES NOT IMPROVE V1",
    }

    predictions = pd.read_parquet(OUTPUT / "validation/validation_predictions.parquet")
    expected = {
        "model", "fold", "week", "model_node_id", "canonical_node_id", "observed_presence", "observed_count",
        "first_ever_positive_flag", "previously_positive_flag", "predicted_probability",
        "predicted_conditional_mean", "predicted_unconditional_mean",
    }
    assert expected.issubset(predictions.columns), sorted(expected - set(predictions.columns))
    assert set(predictions["model"].unique()) == {"M0", "M1", "M2"}
    assert set(predictions["fold"].unique()) == {1, 2, 3, 4, 5, 6}
    assert len(predictions) == 55 * 10037 * 3
    assert predictions[["predicted_probability", "predicted_conditional_mean", "predicted_unconditional_mean"]].notna().all().all()
    assert predictions["predicted_probability"].between(0, 1).all()
    assert (predictions["predicted_conditional_mean"] >= 0).all()
    assert (predictions["predicted_unconditional_mean"] >= 0).all()
    assert np.allclose(
        predictions["predicted_unconditional_mean"],
        predictions["predicted_probability"] * predictions["predicted_conditional_mean"],
        rtol=1e-6,
        atol=1e-10,
    )
    positives = predictions["observed_presence"].astype(bool)
    assert (~(predictions["first_ever_positive_flag"].astype(bool) & predictions["previously_positive_flag"].astype(bool))).all()
    assert (predictions.loc[positives, "first_ever_positive_flag"].astype(bool) | predictions.loc[positives, "previously_positive_flag"].astype(bool)).all()

    front = pd.read_parquet(OUTPUT / "front_features/causal_front_features.parquet")
    front_required = {
        "week", "model_node_id", "canonical_node_id", "distance_to_any_prior_positive_km",
        "distance_to_prev4_positive_km", "weeks_since_detection_within_50km",
        "any_prior_positive_available", "prev4_positive_available",
        "detection_within_50km_ever_available", "history_cutoff_week",
    }
    assert front_required.issubset(front.columns), sorted(front_required - set(front.columns))
    assert front[["week", "model_node_id"]].duplicated().sum() == 0
    assert len(front) == 81 * 10037
    assert np.isfinite(front.select_dtypes(include=[np.number]).to_numpy()).all()
    cutoff_by_week = front.groupby("week")["history_cutoff_week"].nunique()
    assert (cutoff_by_week == 1).all()
    for week, cutoff in front.groupby("week", sort=True)["history_cutoff_week"].first().items():
        year, iso_week = (int(part) for part in week.split("-W"))
        previous = date.fromisocalendar(year, iso_week, 1) - timedelta(weeks=1)
        expected_cutoff = f"{previous.isocalendar().year:04d}-W{previous.isocalendar().week:02d}"
        assert cutoff == expected_cutoff, (week, cutoff, expected_cutoff)

    reproduction = pd.read_csv(OUTPUT / "metrics/v1_reproduction.csv")
    assert reproduction["joint_nll_abs_diff"].max() <= 1e-3
    assert reproduction["brier_skill_abs_diff"].max() <= 1e-3

    checksums = pd.read_csv(OUTPUT / "manifests/task3b_v2a_checksums.csv")
    assert len(checksums) > 0
    for row in checksums.itertuples(index=False):
        path = OUTPUT / row.relative_path
        assert path.is_file(), row.relative_path
        assert sha256(path) == row.sha256, row.relative_path

    assert sha256(SOURCE) == SOURCE_SHA
    print({"status": "PASS", "prediction_rows": len(predictions), "front_rows": len(front), "git_sha": head})


if __name__ == "__main__":
    main()
