"""Focused synthetic tests for the STRUCTURED_A3 observation-key audit."""

import sys
from collections import Counter
from decimal import InvalidOperation
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "analysis" / "structured_a3_data_refresh_2026w44" / "scripts"))
import observation_duplicate_precision_audit as audit  # noqa: E402


def row(day: str, lon: str, lat: str, host: str = "cattle") -> dict[str, str]:
    return {"date": day, "host": host, "lon": lon, "lat": lat}


class ObservationDuplicatePrecisionTests(unittest.TestCase):
    def test_exact_duplicate_records_and_count_definitions(self):
        rows = [row("2026-03-01", "-100.12345", "20.5")] * 3
        metrics = audit.key_metrics(audit.record_key(item, ["date", "host", "lon", "lat"]) for item in rows)
        self.assertEqual(metrics, {
            "Total rows": 3,
            "Unique keys": 1,
            "Duplicate groups": 1,
            "Rows in duplicate groups": 3,
            "Redundant rows": 2,
            "Maximum multiplicity": 3,
        })

    def test_trailing_zeros_are_textually_distinct_but_exact_decimal_equal(self):
        first, second = "-100.123450", "-100.12345"
        self.assertNotEqual(first, second)
        self.assertEqual(audit.canonical_decimal(first), audit.canonical_decimal(second))
        self.assertEqual(len({first, second}), 2)
        self.assertEqual(len({audit.canonical_decimal(value) for value in (first, second)}), 1)

    def test_final_retained_decimal_digit_remains_distinct(self):
        first, second = "-100.12345", "-100.12346"
        self.assertNotEqual(audit.canonical_decimal(first), audit.canonical_decimal(second))
        self.assertNotEqual(
            audit.float_key(row("2026-03-01", first, "20.5")),
            audit.float_key(row("2026-03-01", second, "20.5")),
        )

    def test_coordinates_collide_only_after_deliberate_rounding(self):
        first, second = "-100.123441", "-100.123444"
        self.assertNotEqual(audit.canonical_decimal(first), audit.canonical_decimal(second))
        self.assertEqual(audit.rounded_decimal(first, 5), audit.rounded_decimal(second, 5))

    def test_same_coordinates_on_different_dates_are_distinct_keys(self):
        keys = [audit.decimal_key(row(day, "-100.1", "20.2"), "calendar")
                for day in ("2026-03-01", "2026-03-02")]
        self.assertEqual(audit.key_metrics(keys)["Unique keys"], 2)
        self.assertEqual(audit.key_metrics(keys)["Duplicate groups"], 0)

    def test_distinct_coordinates_on_same_date_are_distinct_keys(self):
        keys = [audit.decimal_key(row("2026-03-01", lon, "20.2"), "calendar")
                for lon in ("-100.1", "-100.2")]
        self.assertEqual(audit.key_metrics(keys)["Unique keys"], 2)
        self.assertEqual(audit.key_metrics(keys)["Duplicate groups"], 0)

    def test_host_difference_is_not_a_unique_coordinate_key(self):
        records = [row("2026-03-01", "-100.1", "20.2", "cattle"),
                   row("2026-03-01", "-100.1", "20.2", "goat")]
        full = audit.key_metrics(audit.record_key(item, ["date", "host", "lon", "lat"]) for item in records)
        coordinate = audit.key_metrics(audit.decimal_key(item, "calendar") for item in records)
        self.assertEqual(full["Duplicate groups"], 0)
        self.assertEqual(coordinate["Duplicate groups"], 1)
        self.assertEqual(coordinate["Rows in duplicate groups"], 2)

    def test_float64_can_collapse_distinct_exact_decimal_coordinates(self):
        first, second = "-100.12345678901234567", "-100.12345678901234568"
        self.assertNotEqual(audit.canonical_decimal(first), audit.canonical_decimal(second))
        self.assertEqual(float(first), float(second))

    def test_release_overlap_is_not_within_dataset_duplication(self):
        release_a = [("2026-03-01", "x"), ("2026-03-01", "x")]
        release_b = [("2026-03-01", "x")]
        within_a = audit.key_metrics(release_a)
        within_b = audit.key_metrics(release_b)
        overlap = sum(min(count, Counter(release_b)[key]) for key, count in Counter(release_a).items())
        self.assertEqual(within_a["Duplicate groups"], 1)
        self.assertEqual(within_b["Duplicate groups"], 0)
        self.assertEqual(overlap, 1)

    def test_calendar_date_conversion_can_create_a_collision(self):
        first = row("2026-03-01", "-100.1", "20.2")
        second = row("2026-03-01T12:30:00", "-100.1", "20.2")
        raw_keys = [(item["date"], audit.canonical_decimal(item["lon"]), audit.canonical_decimal(item["lat"]))
                    for item in (first, second)]
        calendar_keys = [audit.decimal_key(item, "calendar") for item in (first, second)]
        self.assertEqual(audit.key_metrics(raw_keys)["Duplicate groups"], 0)
        self.assertEqual(audit.key_metrics(calendar_keys)["Duplicate groups"], 1)

    def test_scientific_and_plain_decimal_forms_canonicalize_exactly(self):
        self.assertEqual(audit.canonical_decimal("1.2345e2"), audit.canonical_decimal("123.4500"))
        self.assertEqual(audit.canonical_decimal("-0.000"), "0e0")

    def test_invalid_decimal_coordinates_are_rejected(self):
        for bad in ("", "nan", "inf", "1,25", "12.3.4"):
            with self.subTest(bad=bad):
                with self.assertRaises((InvalidOperation, ValueError)):
                    audit.canonical_decimal(bad)
