from __future__ import annotations

import numpy as np
from pathlib import Path

from task2b_pipeline import assert_development_only, assert_dataset, load_data, make_masks


if __name__ == "__main__":
    data = load_data(Path("/project/disease_ecology/STGNN-output"))
    assert_dataset(data)
    train, valid = make_masks(data, 1, "temporal")
    if np.any(train & valid): raise AssertionError("temporal masks overlap")
    if np.any(valid[107:]): raise AssertionError("final test appears in development validation")
    try:
        assert_development_only(np.pad(np.ones((26, 1), dtype=bool), ((107, 0), (0, 16755))), data, "development")
    except RuntimeError:
        pass
    else:
        raise AssertionError("final-test guard did not reject predictive mask")
    for spatial_fold in range(5):
        spatial_train, spatial_eval = make_masks(data, 1, "spatial", spatial_fold)
        development = np.asarray(data["splits"]["development"]["indices"])
        if not np.array_equal((spatial_train | spatial_eval)[development], np.ones_like((spatial_train | spatial_eval)[development], dtype=bool)): raise AssertionError("spatial coverage")
        if np.any(spatial_train & spatial_eval): raise AssertionError("spatial overlap")
    print("Task-2B contract/masking smoke: PASS")
