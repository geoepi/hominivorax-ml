"""Regression contract for the corrected P3 human-readable frontier summary."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT = REPO_ROOT / "analysis" / "p3_robustness" / "p3_robustness_report.md"
FRONTIER = REPO_ROOT / "analysis" / "p3_robustness" / "results" / "frontier_sensitivity_metrics.csv"


def test_p3_frontier_report_aggregates_machine_readable_counts() -> None:
    report = REPORT.read_text(encoding="utf-8")
    assert "F0 h=1 aggregate positive counts across all origins were:" in report

    counts: dict[str, int] = defaultdict(int)
    with FRONTIER.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["definition"] == "F0_reference" and row["horizon"] == "1":
                counts[row["frontier_class"]] += int(row["positives"])

    summary = next(line for line in report.splitlines() if "F0 h=1 aggregate positive counts" in line)
    for frontier_class, positives in sorted(counts.items()):
        assert summary.count(f"{frontier_class}={positives}") == 1
    assert summary.count("previously_occupied=") == 1
    assert summary.count("previously_unoccupied=") == 1
