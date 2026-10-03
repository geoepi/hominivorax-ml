from __future__ import annotations

import numpy as np

from task2b_pipeline import assert_dataset, build_features, load_data, make_masks


if __name__ == "__main__":
    data = load_data(__import__("pathlib").Path("/project/disease_ecology/STGNN-output"))
    assert_dataset(data)
    features, prep = build_features(data, 1)
    if features.shape != (185, 16756, 24): raise AssertionError(features.shape)
    if not np.isfinite(features).all(): raise AssertionError("non-finite transformed feature")
    if prep["indicators_unscaled"] is not True or prep["calendar_unscaled"] is not True: raise AssertionError("fold transform contract")
    for regime in ["temporal", "spatial", "combined"]:
        train, evaluation = make_masks(data, 1, regime, 0 if regime != "temporal" else None)
        if train.shape != (133, 16756) or evaluation.shape != (133, 16756): raise AssertionError(regime)
        if np.any(evaluation[107:]): raise AssertionError("final-test mask contamination")
    print("Task-2B data/split smoke: PASS", features.shape)
