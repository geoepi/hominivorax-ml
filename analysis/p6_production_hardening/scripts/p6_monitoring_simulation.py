#!/usr/bin/env python3
"""Exercise fixed P6 monitoring states without changing scientific thresholds."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import p6_production as p6


CONFIG = {"drift": {"support_proportion_warning_absolute": 0.10, "support_proportion_review_absolute": 0.20, "distribution_relative_warning": 0.25, "distribution_relative_review": 0.50}}
BASELINE = {"support_class_proportions": {"SUPPORTED": 0.70, "CAUTION": 0.20, "EXTRAPOLATIVE": 0.10}, "occurrence_summary": {"mean": 0.05}, "expected_count_summary": {"mean": 0.20}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    warning = {"support_class_proportions": {"SUPPORTED": 0.58, "CAUTION": 0.22, "EXTRAPOLATIVE": 0.20}, "occurrence_summary": {"mean": 0.05}, "expected_count_summary": {"mean": 0.20}}
    review = {"support_class_proportions": {"SUPPORTED": 0.45, "CAUTION": 0.25, "EXTRAPOLATIVE": 0.30}, "occurrence_summary": {"mean": 0.08}, "expected_count_summary": {"mean": 0.35}}
    result = {"baseline": p6.drift_state(BASELINE, None, CONFIG), "warning_fixture": p6.drift_state(warning, BASELINE, CONFIG), "review_fixture": p6.drift_state(review, BASELINE, CONFIG), "thresholds_unchanged": True, "automated_retraining": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
