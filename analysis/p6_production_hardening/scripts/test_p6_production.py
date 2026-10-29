#!/usr/bin/env python3
"""Standard-library unittest coverage for P6 contract controls."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p6_production as p6


class P6ContractTests(unittest.TestCase):
    def test_previous_week_handles_iso_year_boundary(self):
        self.assertEqual(p6.previous_week("2025-W01"), "2024-W52")
        self.assertEqual(p6.previous_week("2026-W01"), "2025-W52")

    def test_e0_changes_only_environment_for_target_weeks(self):
        labels = ["2025-W52", "2026-W01", "2026-W02", "2026-W03", "2026-W04"]
        features = np.arange(len(labels) * 10037 * 34, dtype=float).reshape(len(labels), 10037, 34)
        front = pd.DataFrame({"history_cutoff_week": ["2025-W52"] * (len(labels) * 10037)})
        bundle = {"labels": labels, "features": features, "front": front}
        observed, meta = p6.e0_features(bundle, "2026-W01")
        self.assertEqual(meta["latest_environment_week"], "2025-W52")
        np.testing.assert_array_equal(observed[2, :, :12], features[0, :, :12])
        np.testing.assert_array_equal(observed[3, :, :12], features[0, :, :12])
        np.testing.assert_array_equal(observed[4, :, :12], features[0, :, :12])
        np.testing.assert_array_equal(observed[1, :, 12:], features[1, :, 12:])
        np.testing.assert_array_equal(observed[0], features[0])

    def test_output_validation_rejects_wrong_schema(self):
        frame = pd.DataFrame({"wrong": [1]})
        with self.assertRaises(p6.P6Error) as error:
            p6.validate_output(frame, "2026-W16", "run")
        self.assertEqual(error.exception.code, "OUTPUT_SCHEMA_INVALID")

    def test_drift_thresholds_are_deterministic(self):
        config = {"drift": {"support_proportion_warning_absolute": .1, "support_proportion_review_absolute": .2, "distribution_relative_warning": .25, "distribution_relative_review": .5}}
        monitor = {"support_class_proportions": {"SUPPORTED": .5, "CAUTION": .2, "EXTRAPOLATIVE": .3}, "occurrence_summary": {"mean": .1}, "expected_count_summary": {"mean": 1.0}}
        reference = {"support_class_proportions": {"SUPPORTED": .25, "CAUTION": .2, "EXTRAPOLATIVE": .55}, "occurrence_summary": {"mean": .1}, "expected_count_summary": {"mean": 1.0}}
        result = p6.drift_state(monitor, reference, config)
        self.assertEqual(result["state"], "DRIFT_REVIEW_REQUIRED")
        self.assertEqual(result["action"], "REVIEW_REQUIRED")

    def test_atomic_json_has_no_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            p6.write_json(path, {"status": "ok"})
            self.assertEqual(json.loads(path.read_text())["status"], "ok")
            self.assertEqual(list(Path(directory).glob("*.tmp-*")), [])


if __name__ == "__main__":
    unittest.main()
