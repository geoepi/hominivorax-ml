#!/usr/bin/env python3
"""Aggregate-only re-audit of the corrected STRUCTURED_A3 observation source.

This runner reuses the checksum-gated exact-decimal and duplicate-count helpers
from observation_duplicate_precision_audit.py. It emits aggregate CSV/JSON
outputs only; it never writes source rows or coordinates.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import observation_duplicate_precision_audit as audit


PREVIOUS_UPDATED_SHA256 = "8fd21f9db11db3df20596fe7ad0b4cbbc8b895fbaad6f702c847ed5a05dd19fc"
CORRECTED_UPDATED_SHA256 = "2f9cf04ffe01712b8e5498d809f542d159ff1cb33ae8b567aa6644e9c4f05de5"
HISTORICAL_SHA256 = "a3d55f3ddf867087b578df803920bf59c6c303fa695e3218a5f3463e596d497e"
PREVIOUS_AUDIT_COMMIT = "b39e44ba5da5dd6dea5c0c26072d68b66e2797ba"
AUDIT_VERSION = "1.0.1"
EXPECTED_HEADER = ["date", "host", "lon", "lat"]
W01_2025 = (2025, 1)
W16_2026 = (2026, 16)
W44_2026 = (2026, 44)

SCOPES = (
    "Entire corrected source",
    "Before 2025-W01",
    "Original W16 training horizon",
    "Extended W44 training horizon",
    "After 2026-W16",
    "After 2026-W44",
)

SCOPE_TO_PREVIOUS = {
    "Entire corrected source": "Entire observation dataset",
    "Before 2025-W01": "Before original W16 training horizon",
    "Original W16 training horizon": "Original W16 training horizon",
    "After 2026-W16": "After original W16 training horizon",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def date_and_week(row: dict[str, str]) -> tuple[str | None, tuple[int, int] | None]:
    normalized = audit.date_calendar_key(row["date"])
    if normalized is None:
        return None, None
    iso = date.fromisoformat(normalized).isocalendar()
    return normalized, (iso.year, iso.week)


def scope_contains(scope: str, week: tuple[int, int] | None) -> bool:
    if scope == "Entire corrected source":
        return True
    if week is None:
        return False
    if scope == "Before 2025-W01":
        return week < W01_2025
    if scope == "Original W16 training horizon":
        return W01_2025 <= week <= W16_2026
    if scope == "Extended W44 training horizon":
        return W01_2025 <= week <= W44_2026
    if scope == "After 2026-W16":
        return week > W16_2026
    if scope == "After 2026-W44":
        return week > W44_2026
    raise ValueError(f"Unknown temporal scope: {scope}")


def safe_decimal_key(row: dict[str, str]) -> tuple[str, str, str]:
    normalized = audit.date_calendar_key(row["date"])
    day = normalized if normalized is not None else "UNPARSED_DATE:" + row["date"]
    try:
        lon = audit.canonical_decimal(row["lon"])
    except (InvalidOperation, ValueError):
        lon = "INVALID_LON:" + row["lon"]
    try:
        lat = audit.canonical_decimal(row["lat"])
    except (InvalidOperation, ValueError):
        lat = "INVALID_LAT:" + row["lat"]
    return day, lon, lat


def safe_float_key(row: dict[str, str]) -> tuple[Any, ...]:
    normalized = audit.date_calendar_key(row["date"])
    day: Any = normalized if normalized is not None else "UNPARSED_DATE:" + row["date"]
    values: list[Any] = []
    for name in ("lon", "lat"):
        try:
            parsed = float(row[name].strip())
            values.append(parsed if math.isfinite(parsed) else "NONFINITE:" + row[name])
        except (ValueError, OverflowError):
            values.append("INVALID:" + row[name])
    return day, values[0], values[1]


def conflicting_host_groups(keys: list[tuple[Any, ...]], rows: list[dict[str, str]]) -> int:
    multiplicity: Counter[tuple[Any, ...]] = Counter(keys)
    hosts: dict[tuple[Any, ...], set[str]] = defaultdict(set)
    for key, row in zip(keys, rows, strict=True):
        hosts[key].add(row["host"])
    return sum(count > 1 and len(hosts[key]) > 1 for key, count in multiplicity.items())


def source_metrics(dataset: str, rows: list[dict[str, str]], header: list[str]):
    indexed: list[dict[str, Any]] = []
    for row in rows:
        normalized, week = date_and_week(row)
        indexed.append({
            "row": row,
            "date": normalized,
            "week": week,
            "complete": tuple(row[column] for column in header),
            "raw": (row["date"], row["lon"], row["lat"]),
            "exact": safe_decimal_key(row),
            "float": safe_float_key(row),
        })

    summary: list[dict[str, Any]] = []
    scope_metrics: dict[tuple[str, str], dict[str, Any]] = {}
    for scope in SCOPES:
        selected = [item for item in indexed if scope_contains(scope, item["week"])]
        current_rows = [item["row"] for item in selected]
        complete_keys = [item["complete"] for item in selected]
        exact_keys = [item["exact"] for item in selected]
        host_conflicts = conflicting_host_groups(exact_keys, current_rows)
        complete_groups = audit.key_metrics(complete_keys)["Duplicate groups"]
        methods = (
            ("Complete source record: raw character fields", complete_keys),
            ("Raw character (date,lon,lat)", [item["raw"] for item in selected]),
            ("Exact decimal; calendar-date key", exact_keys),
            ("Standard float64; calendar-date key", [item["float"] for item in selected]),
        )
        for method, keys in methods:
            metrics = audit.key_metrics(keys)
            metrics["Complete-record duplicate groups"] = complete_groups
            metrics["Duplicate groups with conflicting host attributes"] = host_conflicts
            row = {
                "Dataset": dataset,
                "Temporal subset": scope,
                "Comparison method": method,
                **metrics,
            }
            summary.append(row)
            scope_metrics[(scope, method)] = metrics
    return indexed, summary, scope_metrics


def integrity_summary(rows: list[dict[str, str]], header: list[str], path: Path) -> dict[str, Any]:
    blank_by_field = {column: 0 for column in header}
    valid_dates: list[str] = []
    date_whitespace = date_time_count = non_iso_date_count = invalid_dates = 0
    coordinate_parse_errors = {"lon": 0, "lat": 0}
    nonfinite = {"lon": 0, "lat": 0}
    out_of_range = {"lon": 0, "lat": 0}
    coordinate_values: dict[str, list[Decimal]] = {"lon": [], "lat": []}
    valid_coordinate_rows = 0
    for row in rows:
        for column in header:
            blank_by_field[column] += int(not row[column].strip())
        raw_date = row["date"]
        date_whitespace += int(raw_date != raw_date.strip())
        normalized = audit.date_calendar_key(raw_date)
        if normalized is None:
            invalid_dates += 1
        else:
            valid_dates.append(normalized)
            date_time_count += int(len(raw_date.strip()) > 10)
            non_iso_date_count += int(raw_date.strip() != normalized)
        row_coordinates_valid = True
        for axis, lower, upper in (("lon", Decimal(-180), Decimal(180)),
                                   ("lat", Decimal(-90), Decimal(90))):
            try:
                value = Decimal(row[axis].strip())
            except (InvalidOperation, ValueError):
                coordinate_parse_errors[axis] += 1
                row_coordinates_valid = False
                continue
            if not value.is_finite():
                nonfinite[axis] += 1
                row_coordinates_valid = False
                continue
            if value < lower or value > upper:
                out_of_range[axis] += 1
                row_coordinates_valid = False
            coordinate_values[axis].append(value)
        valid_coordinate_rows += int(row_coordinates_valid)

    try:
        import pandas as pd

        inferred_dtypes = {str(key): str(value) for key, value in pd.read_csv(path).dtypes.items()}
        pandas_version = pd.__version__
    except Exception as exc:  # preserve the audit result if only dtype profiling is unavailable
        inferred_dtypes = {"profile_status": "unavailable"}
        pandas_version = None
        dtype_profile_error = type(exc).__name__
    else:
        dtype_profile_error = None

    return {
        "expected_columns": EXPECTED_HEADER,
        "observed_columns": header,
        "schema_matches_expected_order": header == EXPECTED_HEADER,
        "row_count": len(rows),
        "blank_fields_by_column": blank_by_field,
        "blank_field_count": sum(blank_by_field.values()),
        "invalid_calendar_dates": invalid_dates,
        "date_records_with_surrounding_whitespace": date_whitespace,
        "date_time_records": date_time_count,
        "non_iso_calendar_date_text_records": non_iso_date_count,
        "earliest_observation_date": min(valid_dates) if valid_dates else None,
        "latest_observation_date": max(valid_dates) if valid_dates else None,
        "unique_calendar_dates": len(set(valid_dates)),
        "coordinate_parse_errors": coordinate_parse_errors,
        "nonfinite_coordinate_values": nonfinite,
        "out_of_range_coordinate_values": out_of_range,
        "globally_valid_coordinate_rows": valid_coordinate_rows,
        "finite_coordinate_value_counts": {
            axis: len(values) for axis, values in coordinate_values.items()
        },
        "pandas_default_inferred_dtypes": inferred_dtypes,
        "pandas_version": pandas_version,
        "dtype_profile_error": dtype_profile_error,
        "source_field_definition_note": "CSV fields have no declared schema types; the raw audit parser retains all fields as strings.",
    }


def weekly_inventory(indexed: list[dict[str, Any]], header: list[str]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for item in indexed:
        if item["week"] is not None:
            grouped[item["week"]].append(item)
    output: list[dict[str, Any]] = []
    if not grouped:
        return []
    first_week = min(grouped)
    last_week = max(grouped)
    monday = date.fromisocalendar(first_week[0], first_week[1], 1)
    last_monday = date.fromisocalendar(last_week[0], last_week[1], 1)
    weeks: list[tuple[int, int]] = []
    while monday <= last_monday:
        iso = monday.isocalendar()
        weeks.append((iso.year, iso.week))
        monday = date.fromordinal(monday.toordinal() + 7)
    for year_week in weeks:
        items = grouped.get(year_week, [])
        exact = [item["exact"] for item in items]
        complete = [item["complete"] for item in items]
        metrics = audit.key_metrics(exact)
        output.append({
            "ISO week": f"{year_week[0]}-W{year_week[1]:02d}",
            "Total observations": len(items),
            "Unique exact-decimal observation keys": metrics["Unique keys"],
            "Duplicate-key groups": metrics["Duplicate groups"],
            "Rows in duplicate-key groups": metrics["Rows in duplicate groups"],
            "Redundant observation-key rows": metrics["Redundant rows"],
            "Maximum key multiplicity": metrics["Maximum multiplicity"],
            "Complete-record duplicate groups": audit.key_metrics(complete)["Duplicate groups"],
            "Duplicate groups with conflicting host attributes": conflicting_host_groups(
                exact, [item["row"] for item in items]
            ),
        })
    return output


def historical_comparison(
    updated_index: list[dict[str, Any]], historical_index: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    # Reuse each source row's cached key and week; keep only lightweight row references
    # in each scope to bound memory use.
    current_scopes = {
        scope: [item for item in updated_index if scope_contains(scope, item["week"])]
        for scope in SCOPES
    }
    historical_scopes = {
        scope: [item for item in historical_index if scope_contains(scope, item["week"])]
        for scope in SCOPES
    }
    scope_rows: list[dict[str, Any]] = []
    for scope in SCOPES:
        current = current_scopes[scope]
        old = historical_scopes[scope]
        current_keys = Counter(item["exact"] for item in current)
        old_keys = Counter(item["exact"] for item in old)
        shared = set(current_keys) & set(old_keys)
        current_complete = Counter(item["complete"] for item in current)
        old_complete = Counter(item["complete"] for item in old)
        current_hosts: dict[tuple[Any, ...], Counter[str]] = defaultdict(Counter)
        old_hosts: dict[tuple[Any, ...], Counter[str]] = defaultdict(Counter)
        for item in current:
            current_hosts[item["exact"]][item["row"]["host"]] += 1
        for item in old:
            old_hosts[item["exact"]][item["row"]["host"]] += 1
        scope_rows.append({
            "Temporal subset": scope,
            "Corrected rows": len(current),
            "Corrected unique keys": len(current_keys),
            "Corrected duplicate-key groups": sum(v > 1 for v in current_keys.values()),
            "Historical rows": len(old),
            "Historical unique keys": len(old_keys),
            "Historical duplicate-key groups": sum(v > 1 for v in old_keys.values()),
            "Unique keys shared between releases": len(shared),
            "Corrected-only unique keys": len(set(current_keys) - set(old_keys)),
            "Historical-only unique keys": len(set(old_keys) - set(current_keys)),
            "Matched key multiplicity": sum(min(current_keys[key], old_keys[key]) for key in shared),
            "Corrected-only key multiplicity": sum(max(0, n - old_keys[key]) for key, n in current_keys.items()),
            "Historical-only key multiplicity": sum(max(0, n - current_keys[key]) for key, n in old_keys.items()),
            "Exact complete-record overlap multiplicity": sum(
                min(n, old_complete[key]) for key, n in current_complete.items()
            ),
            "Shared keys with different host sets": sum(
                set(current_hosts[key]) != set(old_hosts[key]) for key in shared
            ),
            "Shared keys with different host multiplicities": sum(
                current_hosts[key] != old_hosts[key] for key in shared
            ),
            "Interpretation": "Cross-release overlap and revision; not within-source duplication.",
        })

    current_weekly: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    historical_weekly: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for item in current_scopes["Entire corrected source"]:
        if item["week"] is not None:
            current_weekly[item["week"]].append(item)
    for item in historical_scopes["Entire corrected source"]:
        if item["week"] is not None:
            historical_weekly[item["week"]].append(item)
    week_rows: list[dict[str, Any]] = []
    for week in sorted(set(current_weekly) | set(historical_weekly)):
        current = current_weekly[week]
        old = historical_weekly[week]
        current_keys = Counter(item["exact"] for item in current)
        old_keys = Counter(item["exact"] for item in old)
        week_rows.append({
            "ISO week": f"{week[0]}-W{week[1]:02d}",
            "Corrected observations": len(current),
            "Historical observations": len(old),
            "Observation row difference (corrected minus historical)": len(current) - len(old),
            "Corrected unique observation keys": len(current_keys),
            "Historical unique observation keys": len(old_keys),
            "Unique-key difference (corrected minus historical)": len(current_keys) - len(old_keys),
            "Corrected duplicate-key groups": sum(v > 1 for v in current_keys.values()),
            "Historical duplicate-key groups": sum(v > 1 for v in old_keys.values()),
            "Unique keys shared": len(set(current_keys) & set(old_keys)),
        })
    return scope_rows, week_rows


def read_previous_baseline(
    summary_path: Path, manifest_path: Path, precision_path: Path
) -> tuple[list[dict[str, str]], dict[str, Any], list[dict[str, str]]]:
    with manifest_path.open(encoding="utf-8") as stream:
        manifest = json.load(stream)
    if manifest["source_integrity"]["updated"]["sha256"] != PREVIOUS_UPDATED_SHA256:
        raise ValueError("Previous audit manifest checksum does not match the recorded baseline.")
    if manifest["source_integrity"]["updated"]["row_count"] != 167078:
        raise ValueError("Previous audit manifest row count does not match the recorded baseline.")
    with summary_path.open(encoding="utf-8-sig", newline="") as stream:
        summary = list(csv.DictReader(stream))
    with precision_path.open(encoding="utf-8-sig", newline="") as stream:
        precision = list(csv.DictReader(stream))
    return summary, manifest, precision


def prior_version_comparison(
    current_metrics: dict[tuple[str, str], dict[str, Any]],
    previous_summary: list[dict[str, str]],
    corrected_sha: str,
) -> list[dict[str, Any]]:
    old_by_method = {
        (row["Temporal subset"], row["Comparison method"]): row
        for row in previous_summary
        if row["Dataset"] == "Updated 2026-11-13"
    }
    output: list[dict[str, Any]] = []
    for scope in SCOPES:
        old_scope = SCOPE_TO_PREVIOUS.get(scope)
        old_key = old_by_method.get((old_scope, "Exact decimal; calendar-date key")) if old_scope else None
        old_full = old_by_method.get((old_scope, "Complete source record: raw character fields")) if old_scope else None
        current = current_metrics[(scope, "Exact decimal; calendar-date key")]
        current_full = current_metrics[(scope, "Complete source record: raw character fields")]
        prev_values = {
            "Previous rows": int(old_key["Total rows"]) if old_key else None,
            "Previous unique keys": int(old_key["Unique keys"]) if old_key else None,
            "Previous duplicate-key groups": int(old_key["Duplicate groups"]) if old_key else None,
            "Previous redundant key rows": int(old_key["Redundant rows"]) if old_key else None,
            "Previous complete-record duplicate groups": int(old_full["Duplicate groups"]) if old_full else None,
            "Previous conflicting-host groups": (
                int(old_key["Duplicate groups"]) - int(old_full["Duplicate groups"])
                if old_key and old_full else None
            ),
        }
        current_values = {
            "Corrected rows": current["Total rows"],
            "Corrected unique keys": current["Unique keys"],
            "Corrected duplicate-key groups": current["Duplicate groups"],
            "Corrected redundant key rows": current["Redundant rows"],
            "Corrected complete-record duplicate groups": current_full["Duplicate groups"],
            "Corrected conflicting-host groups": current["Duplicate groups with conflicting host attributes"],
        }
        row = {
            "Temporal subset": scope,
            "Previous source SHA-256": PREVIOUS_UPDATED_SHA256,
            "Corrected source SHA-256": corrected_sha,
            **prev_values,
            **current_values,
            "Row delta": current_values["Corrected rows"] - prev_values["Previous rows"] if old_key else None,
            "Unique-key delta": current_values["Corrected unique keys"] - prev_values["Previous unique keys"] if old_key else None,
            "Duplicate-group delta": current_values["Corrected duplicate-key groups"] - prev_values["Previous duplicate-key groups"] if old_key else None,
            "Redundant-row delta": current_values["Corrected redundant key rows"] - prev_values["Previous redundant key rows"] if old_key else None,
            "Retained keys": "NOT_COMPUTABLE",
            "Removed keys": "NOT_COMPUTABLE",
            "Added keys": "NOT_COMPUTABLE",
            "Keys with changed multiplicity": "NOT_COMPUTABLE",
            "Retained keys with host changes": "NOT_COMPUTABLE",
            "Weekly change comparison": "NOT_COMPUTABLE",
            "Comparison status": (
                "AGGREGATE_BASELINE_ONLY; previous source file unavailable"
                if old_key else "NO_PREVIOUS_AGGREGATE_FOR_THIS_SCOPE"
            ),
            "Limitation": "The prior SHA-256 was not found among authorized source snapshots; aggregate counts cannot identify retained or changed keys.",
        }
        output.append(row)
    return output


def precision_profile_changed(
    previous: list[dict[str, str]], current: list[dict[str, Any]]
) -> bool:
    prior = {
        (row["Coordinate"], int(row["Decimal places as written"])): row
        for row in previous if row["Dataset"] == "Updated 2026-11-13"
    }
    now = {
        (row["Coordinate"], int(row["Decimal places as written"])): row
        for row in current if row["Dataset"] == "Corrected 2026-11-13"
    }
    signature_fields = (
        "Record count", "Minimum decimal places", "Maximum decimal places",
        "Records with trailing fractional zeros", "Scientific notation records",
        "Exact values with multiple textual forms", "Distinct exact values collapsed into float64 bins",
    )
    for key in set(prior) | set(now):
        old = prior.get(key)
        new = now.get(key)
        if old is None or new is None:
            return True
        if any(str(old[field]) != str(new[field]) for field in signature_fields):
            return True
    return False


def rounding_sensitivity(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for scope in SCOPES:
        selected = [
            row for row in rows
            if scope_contains(scope, date_and_week(row)[1])
        ]
        reference = audit.key_metrics(safe_decimal_key(row) for row in selected)
        for places in audit.DECIMAL_PLACES:
            keys = (
                (
                    audit.date_calendar_key(row["date"]) or "UNPARSED_DATE:" + row["date"],
                    audit.rounded_decimal(row["lon"], places),
                    audit.rounded_decimal(row["lat"], places),
                )
                for row in selected
            )
            metrics = audit.key_metrics(keys)
            result.append({
                "Dataset": "Corrected 2026-11-13",
                "Temporal subset": scope,
                "Rounding decimal places": places,
                **metrics,
                "Exact decimal reference unique keys": reference["Unique keys"],
                "Additional duplicate groups vs exact reference": metrics["Duplicate groups"] - reference["Duplicate groups"],
                "Additional redundant rows vs exact reference": metrics["Redundant rows"] - reference["Redundant rows"],
                "Rounding rule": "Exact Decimal quantization, ROUND_HALF_EVEN",
            })
    return result


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.updated_sha256 != CORRECTED_UPDATED_SHA256:
        raise ValueError("Corrected source checksum argument does not match the verified re-audit checksum.")
    updated, updated_header, updated_meta = audit.read_source(args.updated_csv, args.updated_sha256)
    historical, historical_header, historical_meta = audit.read_source(args.historical_csv, HISTORICAL_SHA256)
    previous_summary, previous_manifest, previous_precision = read_previous_baseline(
        args.previous_summary_csv, args.previous_manifest_json, args.previous_precision_csv
    )

    updated_integrity = integrity_summary(updated, updated_header, args.updated_csv)
    historical_integrity = integrity_summary(historical, historical_header, args.historical_csv)
    updated_index, updated_summary, updated_metrics = source_metrics(
        "Corrected 2026-11-13", updated, updated_header
    )
    historical_index, historical_summary, historical_metrics = source_metrics(
        "Frozen W16 source 2027-07-31", historical, historical_header
    )
    summary_rows = updated_summary + historical_summary
    precision_rows: list[dict[str, Any]] = []
    for dataset, rows in (("Corrected 2026-11-13", updated), ("Frozen W16 source 2027-07-31", historical)):
        try:
            precision_rows.extend(audit.coordinate_precision_rows(dataset, rows))
        except (InvalidOperation, ValueError):
            pass

    r_rows: list[dict[str, str]] = []
    with args.r_crosscheck_csv.open(encoding="utf-8-sig", newline="") as stream:
        r_rows = list(csv.DictReader(stream))
    r_subset_map = {
        "Entire observation dataset": "Entire corrected source",
        "Original W16 training horizon": "Original W16 training horizon",
        "After original W16 training horizon": "After 2026-W16",
        "Before original W16 training horizon": "Before 2025-W01",
    }
    r_method_map = {
        "Complete source record: raw character fields": "Complete source record: raw character fields",
        "Raw character (date,lon,lat)": "Raw character (date,lon,lat)",
        "Exact decimal; calendar-date key": "Exact decimal; calendar-date key",
    }
    comparison_fields = (
        "Total rows", "Unique keys", "Duplicate groups", "Rows in duplicate groups",
        "Redundant rows", "Maximum multiplicity",
    )
    disagreement_rows: list[str] = []
    checked_r_rows = 0
    for r_row in r_rows:
        scope = r_subset_map.get(r_row["Temporal subset"])
        method = r_method_map.get(r_row["Comparison method"])
        if scope is None or method is None:
            continue
        if r_row["Dataset"] == "Updated 2026-11-13":
            metrics = updated_metrics[(scope, method)]
        elif r_row["Dataset"] == "Frozen W16 source 2027-07-31":
            metrics = historical_metrics[(scope, method)]
        else:
            continue
        checked_r_rows += 1
        for field in comparison_fields:
            if str(metrics[field]) != r_row[field]:
                disagreement_rows.append(f"{r_row['Dataset']}|{scope}|{method}|{field}")

    updated_key = updated_metrics[("Entire corrected source", "Exact decimal; calendar-date key")]
    schema_and_value_checks_pass = (
        updated_integrity["schema_matches_expected_order"]
        and updated_integrity["blank_field_count"] == 0
        and updated_integrity["invalid_calendar_dates"] == 0
        and updated_integrity["date_time_records"] == 0
        and updated_integrity["non_iso_calendar_date_text_records"] == 0
        and sum(updated_integrity["coordinate_parse_errors"].values()) == 0
        and sum(updated_integrity["nonfinite_coordinate_values"].values()) == 0
        and sum(updated_integrity["out_of_range_coordinate_values"].values()) == 0
    )
    if updated_key["Duplicate groups"] > 0:
        source_decision = "OBSERVATION_DUPLICATES_REMAIN"
    elif not schema_and_value_checks_pass:
        source_decision = "OBSERVATION_SOURCE_CORRECTION_INTRODUCED_NEW_ISSUES"
    elif checked_r_rows == 24 and not disagreement_rows:
        source_decision = "OBSERVATION_SOURCE_CORRECTION_VERIFIED"
    else:
        source_decision = "OBSERVATION_SOURCE_REAUDIT_INCONCLUSIVE"

    if source_decision == "OBSERVATION_SOURCE_CORRECTION_VERIFIED":
        # Duplicate success does not resolve completeness, historical provenance, or W29 lineage.
        readiness = "REFRESH_BLOCKED_BY_INPUT_DATA"
    else:
        readiness = "REFRESH_BLOCKED_BY_INPUT_DATA"

    updated_weekly = weekly_inventory(updated_index, updated_header)
    historical_scope_rows, historical_weekly_rows = historical_comparison(
        updated_index, historical_index
    )
    version_rows = prior_version_comparison(updated_metrics, previous_summary, updated_meta["sha256"])
    precision_changed = precision_profile_changed(previous_precision, precision_rows)
    exact_vs_float_fields = (
        "Total rows", "Unique keys", "Duplicate groups", "Rows in duplicate groups",
        "Redundant rows", "Maximum multiplicity",
    )
    exact_vs_float_changed = any(
        updated_metrics[(scope, "Exact decimal; calendar-date key")][field]
        != updated_metrics[(scope, "Standard float64; calendar-date key")][field]
        for scope in SCOPES for field in exact_vs_float_fields
    )
    rounding_rerun = (precision_changed or exact_vs_float_changed) and schema_and_value_checks_pass
    rounding_reason = (
        "Coordinate precision characteristics or exact-decimal/float64 results changed."
        if rounding_rerun else
        "Not rerun: no material precision/key-method change was observed, or source integrity prevented a safe diagnostic."
    )
    rounding_rows = rounding_sensitivity(updated) if rounding_rerun else []

    post_sha = sha256_file(args.updated_csv)
    source_unchanged = post_sha == updated_meta["sha256"] == args.updated_sha256
    if not source_unchanged:
        raise ValueError("Corrected observation source checksum changed during the audit; outputs not written.")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary_fields = [
        "Dataset", "Temporal subset", "Comparison method", "Total rows", "Unique keys",
        "Duplicate groups", "Rows in duplicate groups", "Redundant rows", "Maximum multiplicity",
        "Complete-record duplicate groups", "Duplicate groups with conflicting host attributes",
    ]
    precision_fields = [
        "Dataset", "Coordinate", "Decimal places as written", "Record count",
        "Minimum decimal places", "Maximum decimal places", "Records with trailing fractional zeros",
        "Scientific notation records", "Unique textual values", "Unique exact decimal values",
        "Exact values with multiple textual forms", "Rows using those multiple forms",
        "Distinct exact values collapsed into float64 bins",
    ]
    version_fields = list(version_rows[0])
    history_fields = list(historical_scope_rows[0])
    week_fields = list(updated_weekly[0]) if updated_weekly else ["ISO week", "Total observations"]
    history_week_fields = list(historical_weekly_rows[0]) if historical_weekly_rows else ["ISO week"]

    write_csv(args.output_dir / "observation_corrected_source_summary.csv", summary_rows, summary_fields)
    write_csv(args.output_dir / "observation_corrected_coordinate_precision.csv", precision_rows, precision_fields)
    write_csv(args.output_dir / "observation_source_version_comparison.csv", version_rows, version_fields)
    write_csv(args.output_dir / "observation_corrected_weekly_inventory.csv", updated_weekly, week_fields)
    write_csv(args.output_dir / "observation_historical_release_comparison.csv", historical_scope_rows, history_fields)
    write_csv(args.output_dir / "observation_historical_weekly_comparison.csv", historical_weekly_rows, history_week_fields)
    if r_rows:
        write_csv(
            args.output_dir / "observation_corrected_source_r_crosscheck.csv",
            r_rows,
            list(r_rows[0]),
        )
    if rounding_rows:
        rounding_fields = list(rounding_rows[0])
        write_csv(args.output_dir / "observation_corrected_rounding_sensitivity.csv", rounding_rows, rounding_fields)

    manifest = {
        "audit_name": "STRUCTURED_A3 corrected observation source re-audit",
        "audit_version": AUDIT_VERSION,
        "previous_audit_commit": PREVIOUS_AUDIT_COMMIT,
        "execution_environment": {
            "python": platform.python_version(),
            "pandas": updated_integrity["pandas_version"],
            "r_crosscheck": "Existing base R script invoked through the repository hpc/env_r.sh wrapper.",
            "source_location_policy": "Observation-level data and coordinates remained on Atlas.",
        },
        "source_files": {
            "corrected_updated_source": {
                **updated_meta,
                "sha256_before_audit": updated_meta["sha256"],
                "sha256_after_audit": post_sha,
                "unchanged_during_audit": source_unchanged,
            },
            "historical_w16_source": historical_meta,
            "previous_updated_source": {
                "sha256": PREVIOUS_UPDATED_SHA256,
                "available_as_immutable_source": False,
                "search_scope": "/project/disease_ecology/NWScrewworm; exact prior SHA-256 not present among case_detections/combined_clean_obs*.csv snapshots.",
                "aggregate_baseline": "Prior committed aggregate manifest and summary CSV at the previous audit commit.",
            },
        },
        "integrity": {
            "corrected_source": updated_integrity,
            "historical_source": historical_integrity,
            "coordinate_precision_characteristics_changed": precision_changed,
            "exact_decimal_vs_float64_unique_key_counts_differ": exact_vs_float_changed,
            "rounding_sensitivity_rerun": rounding_rerun,
            "rounding_sensitivity_reason": rounding_reason,
        },
        "comparison_methodology": {
            "python_helper_module": "scripts/observation_duplicate_precision_audit.py (existing committed implementation)",
            "r_helper_script": "scripts/observation_duplicate_precision_audit.R (existing independent implementation)",
            "authoritative_key": "source-local calendar date plus exact Decimal longitude and latitude; host excluded",
            "raw_key": "raw date, lon, lat character strings",
            "complete_record_key": "all source columns as raw character strings",
            "float64_key": "source-local calendar date plus Python double-precision lon and lat",
            "r_crosscheck_rows_compared": checked_r_rows,
            "r_crosscheck_disagreements": disagreement_rows,
            "r_crosscheck_output": "observation_corrected_source_r_crosscheck.csv",
            "previous_version_comparison": "Aggregate baseline only; old source file unavailable; no key identities inferred from counts.",
        },
        "previous_source_comparison": {
            "expected_if_only_redundant_key_rows_removed": {
                "total_records": 164767,
                "unique_observation_keys": 164767,
                "redundant_key_rows": 0,
                "w16_training_records": 91005,
                "w16_training_redundant_rows": 0,
            },
            "expectations_are_conditional": True,
            "version_comparison_csv": "observation_source_version_comparison.csv",
        },
        "historical_release_comparison": {
            "scope_csv": "observation_historical_release_comparison.csv",
            "weekly_csv": "observation_historical_weekly_comparison.csv",
            "cross_release_overlap_is_not_within_source_duplication": True,
        },
        "temporal_availability": {
            "candidate_endpoint": "2026-W44 (2026-10-26 through 2026-11-01)",
            "latest_observed_week": updated_weekly[-1]["ISO week"] if updated_weekly else None,
            "latest_observed_date": updated_integrity["latest_observation_date"],
            "weekly_inventory_csv": "observation_corrected_weekly_inventory.csv",
            "reporting_completeness": "No complete-week declaration was found in the inspected case_detections directory; observed weeks are not treated as complete by presence alone.",
        },
        "decisions": {
            "source_integrity": source_decision,
            "overall_refresh_readiness": readiness,
            "refresh_blockers": [
                "Observation reporting completeness through W44 remains undocumented.",
                "Historical observation revision provenance remains unresolved because the previous source snapshot is unavailable and source revision notes were not found.",
                "W29 artifact-lineage question remains separate and unresolved where applicable.",
            ],
        },
        "validation": {
            "checksums_verified_before_comparison": True,
            "corrected_source_checksum_unchanged_during_audit": source_unchanged,
            "python_r_agreement": checked_r_rows == 24 and not disagreement_rows,
            "focused_synthetic_tests": args.focused_tests_result,
            "source_rows_or_coordinates_emitted": False,
            "model_fitting_or_production_validation": False,
        },
        "outputs": [
            "observation_corrected_source_reaudit.md",
            "observation_corrected_source_summary.csv",
            "observation_source_version_comparison.csv",
            "observation_corrected_weekly_inventory.csv",
            "observation_corrected_source_manifest.json",
            "observation_corrected_coordinate_precision.csv",
            "observation_historical_release_comparison.csv",
            "observation_historical_weekly_comparison.csv",
            "observation_corrected_source_r_crosscheck.csv",
        ],
        "privacy": "Aggregate counts only; no observation-level coordinates or source rows are written.",
    }
    if rounding_rows:
        manifest["outputs"].append("observation_corrected_rounding_sensitivity.csv")
    (args.output_dir / "observation_corrected_source_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--updated-csv", required=True, type=Path)
    parser.add_argument("--historical-csv", required=True, type=Path)
    parser.add_argument("--updated-sha256", default=CORRECTED_UPDATED_SHA256)
    parser.add_argument("--previous-summary-csv", required=True, type=Path)
    parser.add_argument("--previous-manifest-json", required=True, type=Path)
    parser.add_argument("--previous-precision-csv", required=True, type=Path)
    parser.add_argument("--r-crosscheck-csv", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--focused-tests-result", default="NOT_RECORDED")
    args = parser.parse_args()
    manifest = run(args)
    print(json.dumps({
        "source_integrity_decision": manifest["decisions"]["source_integrity"],
        "refresh_readiness": manifest["decisions"]["overall_refresh_readiness"],
        "updated_rows": manifest["source_files"]["corrected_updated_source"]["row_count"],
        "updated_sha256": manifest["source_files"]["corrected_updated_source"]["sha256"],
        "r_crosscheck_rows_compared": manifest["comparison_methodology"]["r_crosscheck_rows_compared"],
        "r_crosscheck_disagreements": len(manifest["comparison_methodology"]["r_crosscheck_disagreements"]),
        "rounding_rerun": manifest["integrity"]["rounding_sensitivity_rerun"],
        "record_level_output_written": False,
    }, separators=(",", ":")))


if __name__ == "__main__":
    main()
