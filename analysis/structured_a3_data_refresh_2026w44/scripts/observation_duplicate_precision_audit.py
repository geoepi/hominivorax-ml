#!/usr/bin/env python3
"""Read-only, aggregate-only duplicate and coordinate precision audit.

The script reads the protected CSVs but never emits record-level rows or
coordinates. Its only files are aggregate CSV/JSON reports in --output-dir.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from pathlib import Path
from typing import Any, Iterable, Sequence


UPDATED_SHA256 = "8fd21f9db11db3df20596fe7ad0b4cbbc8b895fbaad6f702c847ed5a05dd19fc"
HISTORICAL_SHA256 = "a3d55f3ddf867087b578df803920bf59c6c303fa695e3218a5f3463e596d497e"
REQUIRED_COLUMNS = ("date", "host", "lon", "lat")
TRAIN_START = (2025, 1)
TRAIN_END = (2026, 16)
SUBSETS = ("Entire observation dataset", "Original W16 training horizon",
           "After original W16 training horizon", "Before original W16 training horizon")
DECIMAL_PLACES = tuple(range(10, 1, -1))
DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})(?=$|[ T])")
DECIMAL_PARTS = re.compile(
    r"^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$"
)
ISO_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.(\d+))?(?:Z|[+-]\d{2}:?\d{2})?$"
)
TZ_SUFFIX = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$", re.IGNORECASE)


def canonical_decimal(text: str) -> str:
    """Return a lossless base-10 key; equivalent decimal spellings compare equal."""
    value = Decimal(text.strip())
    if not value.is_finite():
        raise ValueError("coordinate is not a finite decimal")
    sign, digits_tuple, exponent = value.as_tuple()
    digits = list(digits_tuple)
    if not any(digits):
        return "0e0"
    while len(digits) > 1 and digits[0] == 0:
        digits.pop(0)
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
        exponent += 1
    digit_text = "".join(str(digit) for digit in digits)
    return f"{'-' if sign else ''}{digit_text}e{exponent}"


def date_calendar_key(text: str) -> str | None:
    """Parse the source-local calendar date without timezone conversion."""
    value = text.strip()
    match = DATE_PREFIX.match(value)
    if match:
        try:
            return date.fromisoformat(match.group(1)).isoformat()
        except ValueError:
            return None
    for pattern in ("%m/%d/%Y", "%Y/%m/%d", "%m/%d/%Y %H:%M:%S",
                    "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    return None


def date_lossless_key(text: str) -> str:
    """Normalize date syntax while retaining date/time and offset distinctions."""
    value = text.strip()
    try:
        return "D:" + date.fromisoformat(value).isoformat()
    except ValueError:
        pass
    if ISO_DATETIME.match(value):
        fraction = ISO_DATETIME.match(value).group(1) or ""
        # Python datetime stores microseconds; keep higher source precision literal.
        if len(fraction) > 6:
            return "RAW:" + value
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc)
                return "T:" + parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
            return "T:" + parsed.isoformat(timespec="microseconds")
        except ValueError:
            return "RAW:" + value
    for pattern in ("%m/%d/%Y", "%Y/%m/%d"):
        try:
            return "D:" + datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    return "RAW:" + value


def temporal_subset(text: str) -> str:
    value = date_calendar_key(text)
    if value is None:
        return "Unclassified date"
    week = date.fromisoformat(value).isocalendar()
    current = (week.year, week.week)
    if TRAIN_START <= current <= TRAIN_END:
        return "Original W16 training horizon"
    if current > TRAIN_END:
        return "After original W16 training horizon"
    return "Before original W16 training horizon"


def key_metrics(keys: Iterable[tuple[Any, ...]], total_rows: int | None = None) -> dict[str, int]:
    counts = Counter(keys)
    multiplicities = [count for count in counts.values() if count > 1]
    total = sum(counts.values()) if total_rows is None else total_rows
    return {
        "Total rows": total,
        "Unique keys": len(counts),
        "Duplicate groups": len(multiplicities),
        "Rows in duplicate groups": sum(multiplicities),
        "Redundant rows": sum(count - 1 for count in multiplicities),
        "Maximum multiplicity": max(multiplicities, default=1),
    }


def record_key(row: dict[str, str], columns: Sequence[str]) -> tuple[str, ...]:
    return tuple(row[column] for column in columns)


def decimal_key(row: dict[str, str], date_mode: str = "lossless") -> tuple[str, str, str]:
    if date_mode == "calendar":
        normalized_date = date_calendar_key(row["date"])
        if normalized_date is None:
            normalized_date = "UNPARSED:" + row["date"]
    else:
        normalized_date = date_lossless_key(row["date"])
    return (normalized_date, canonical_decimal(row["lon"]), canonical_decimal(row["lat"]))


def float_key(row: dict[str, str], date_mode: str = "raw") -> tuple[Any, ...]:
    if date_mode == "calendar":
        normalized_date = date_calendar_key(row["date"]) or "UNPARSED:" + row["date"]
    elif date_mode == "lossless":
        normalized_date = date_lossless_key(row["date"])
    else:
        normalized_date = row["date"]
    longitude = float(row["lon"].strip())
    latitude = float(row["lat"].strip())
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        raise ValueError("coordinate is not a finite floating-point number")
    return normalized_date, longitude, latitude


def read_source(path: Path, expected_sha256: str) -> tuple[list[dict[str, str]], list[str], dict[str, Any]]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    actual_sha = digest.hexdigest()
    if actual_sha != expected_sha256:
        raise ValueError(
            f"source checksum differs; expected {expected_sha256}, found {actual_sha}; "
            "comparison stopped"
        )
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        if reader.fieldnames is None:
            raise ValueError("CSV has no header")
        header = list(reader.fieldnames)
        if len(header) != len(set(header)):
            raise ValueError("CSV has duplicate column names")
        missing = [column for column in REQUIRED_COLUMNS if column not in header]
        if missing:
            raise ValueError(f"CSV lacks required columns: {missing}")
        rows: list[dict[str, str]] = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("CSV row width differs from its header")
            rows.append({column: value for column, value in row.items()})
    stat = path.stat()
    return rows, header, {
        "path": str(path),
        "sha256": actual_sha,
        "size_bytes": stat.st_size,
        "mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "row_count": len(rows),
        "columns": header,
        "parser": "Python csv.DictReader; UTF-8-sig; all fields retained as strings",
    }


def subset_rows(rows: list[dict[str, str]], subset: str) -> list[dict[str, str]]:
    if subset == "Entire observation dataset":
        return rows
    if subset == "Unclassified date":
        return [row for row in rows if temporal_subset(row["date"]) == subset]
    return [row for row in rows if temporal_subset(row["date"]) == subset]


def metric_row(dataset: str, subset: str, method: str, key_columns: str,
               keys: Iterable[tuple[Any, ...]], total_rows: int | None = None) -> dict[str, Any]:
    return {
        "Dataset": dataset,
        "Temporal subset": subset,
        "Comparison method": method,
        "Key columns": key_columns,
        **key_metrics(keys, total_rows),
    }


def source_metric_rows(
    dataset: str, rows: list[dict[str, str]], header: list[str]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for subset in SUBSETS:
        selected = subset_rows(rows, subset)
        result.extend([
            metric_row(dataset, subset, "Complete source record: raw character fields",
                       ",".join(header), (record_key(row, header) for row in selected)),
            metric_row(dataset, subset, "Raw character (date,lon,lat)",
                       "date,lon,lat", ((r["date"], r["lon"], r["lat"]) for r in selected)),
            metric_row(dataset, subset, "Exact decimal; lossless date normalization",
                       "normalized date,Decimal(lon),Decimal(lat)",
                       (decimal_key(r, "lossless") for r in selected)),
            metric_row(dataset, subset, "Exact decimal; calendar-date key",
                       "calendar date,Decimal(lon),Decimal(lat)",
                       (decimal_key(r, "calendar") for r in selected)),
            metric_row(dataset, subset, "Standard float64; raw date",
                       "raw date,float64(lon),float64(lat)",
                       (float_key(r, "raw") for r in selected)),
        ])
    return result


def pandas_previous_reconstruction(path: Path, dataset: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Reconstruct the prior report's described pandas method, not a retained script."""
    import pandas as pd

    frame = pd.read_csv(path)
    if not set(REQUIRED_COLUMNS).issubset(frame.columns):
        raise ValueError("pandas reconstruction did not find required source columns")
    dates = pd.to_datetime(frame["date"], errors="raise")
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_localize(None)
    date_keys = dates.dt.strftime("%Y-%m-%d").tolist()
    hosts = frame["host"].astype(str).tolist()
    longitudes = pd.to_numeric(frame["lon"], errors="raise").astype("float64").tolist()
    latitudes = pd.to_numeric(frame["lat"], errors="raise").astype("float64").tolist()
    all_rows = [
        {"date": d, "host": h, "lon": x, "lat": y}
        for d, h, x, y in zip(date_keys, hosts, longitudes, latitudes, strict=True)
    ]
    output: list[dict[str, Any]] = []
    for subset in SUBSETS:
        selected_idx = [i for i, row in enumerate(all_rows) if subset == "Entire observation dataset"
                        or temporal_subset(row["date"]) == subset]
        selected = [all_rows[i] for i in selected_idx]
        output.extend([
            metric_row(
                dataset, subset, "Reconstructed prior pandas full-row method",
                "date,host,float64(lon),float64(lat)",
                ((r["date"], r["host"], r["lon"], r["lat"]) for r in selected),
            ),
            metric_row(
                dataset, subset, "Reconstructed prior pandas coordinate-key method",
                "date,float64(lon),float64(lat)",
                ((r["date"], r["lon"], r["lat"]) for r in selected),
            ),
        ])
    return output, {
        "parser": "pandas.read_csv with default dtype inference",
        "pandas_version": pd.__version__,
        "date_operation": "pandas.to_datetime(errors='raise').dt.strftime('%Y-%m-%d')",
        "coordinate_operation": "pd.to_numeric(errors='raise').astype('float64')",
        "host_operation": "astype(str)",
        "script_status": "Reconstructed from prior report description; exact prior executable source was not retained in the repository or audit deliverables.",
        "detection_semantics": "The prior report did not record whether its displayed count meant duplicate groups, rows in duplicate groups, or redundant rows; all three are recomputed here.",
    }


def precision_digits(text: str) -> tuple[int | None, bool, bool]:
    value = text.strip()
    match = DECIMAL_PARTS.match(value)
    if not match:
        raise ValueError("coordinate is not a decimal representation")
    fraction = match.group(3) if match.group(2) is not None else match.group(4)
    fraction = fraction or ""
    return len(fraction), bool(fraction.endswith("0")), "e" in value.lower()


def coordinate_precision_rows(dataset: str, rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for coordinate in ("lon", "lat"):
        by_places: dict[int, list[str]] = defaultdict(list)
        raw_by_decimal: dict[str, set[str]] = defaultdict(set)
        float_by_decimal: dict[str, set[str]] = defaultdict(set)
        trailing = scientific = 0
        for row in rows:
            raw = row[coordinate]
            places, has_trailing, has_scientific = precision_digits(raw)
            assert places is not None
            by_places[places].append(raw)
            canonical = canonical_decimal(raw)
            raw_by_decimal[canonical].add(raw)
            float_by_decimal[repr(float(raw))].add(canonical)
            trailing += int(has_trailing)
            scientific += int(has_scientific)
        repeated_forms = {value: forms for value, forms in raw_by_decimal.items() if len(forms) > 1}
        colliding_float_bins = {value: exact for value, exact in float_by_decimal.items() if len(exact) > 1}
        raw_counts = Counter(row[coordinate] for row in rows)
        minimum, maximum = min(by_places), max(by_places)
        for places in sorted(by_places):
            values = by_places[places]
            result.append({
                "Dataset": dataset,
                "Coordinate": coordinate,
                "Decimal places as written": places,
                "Record count": len(values),
                "Minimum decimal places": minimum,
                "Maximum decimal places": maximum,
                "Records with trailing fractional zeros": sum(
                    precision_digits(value)[1] for value in values
                ),
                "Scientific notation records": sum(
                    precision_digits(value)[2] for value in values
                ),
                "Unique textual values": len(set(values)),
                "Unique exact decimal values": len({canonical_decimal(value) for value in values}),
                "Exact values with multiple textual forms": len(repeated_forms),
                "Rows using those multiple forms": sum(
                    raw_counts[text] for forms in repeated_forms.values() for text in forms
                ),
                "Distinct exact values collapsed into float64 bins": sum(
                    len(values) for values in colliding_float_bins.values()
                ),
            })
    return result


def rounded_decimal(text: str, places: int) -> str:
    value = Decimal(text.strip())
    quantum = Decimal(1).scaleb(-places)
    with localcontext() as context:
        context.prec = max(50, len(value.as_tuple().digits) + abs(value.as_tuple().exponent) + places + 8)
        rounded = value.quantize(quantum, rounding=ROUND_HALF_EVEN)
    return canonical_decimal(format(rounded, "f"))


def rounding_rows(dataset: str, rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for subset in SUBSETS:
        selected = subset_rows(rows, subset)
        reference = key_metrics(decimal_key(row, "calendar") for row in selected)
        for places in DECIMAL_PLACES:
            keys = (
                (
                    date_calendar_key(row["date"]) or "UNPARSED:" + row["date"],
                    rounded_decimal(row["lon"], places),
                    rounded_decimal(row["lat"], places),
                )
                for row in selected
            )
            metrics = key_metrics(keys)
            result.append({
                "Dataset": dataset,
                "Temporal subset": subset,
                "Rounding decimal places": places,
                **metrics,
                "Exact decimal reference unique keys": reference["Unique keys"],
                "Additional duplicate groups vs exact reference": metrics["Duplicate groups"] - reference["Duplicate groups"],
                "Additional redundant rows vs exact reference": metrics["Redundant rows"] - reference["Redundant rows"],
                "Rounding rule": "Exact Decimal quantization, ROUND_HALF_EVEN",
            })
    return result


def date_audit(rows: list[dict[str, str]]) -> dict[str, Any]:
    values = [row["date"] for row in rows]
    categories: Counter[str] = Counter()
    leading_or_trailing = 0
    timezone_values = 0
    timestamp_values = 0
    calendar_dates: list[str] = []
    lossless_dates: list[str] = []
    invalid_dates = 0
    for value in values:
        stripped = value.strip()
        leading_or_trailing += int(value != stripped)
        if DATE_PREFIX.match(stripped) and len(stripped) == 10:
            categories["ISO calendar date"] += 1
        elif ISO_DATETIME.match(stripped):
            categories["ISO date-time"] += 1
            timestamp_values += 1
            timezone_values += int(bool(TZ_SUFFIX.search(stripped)))
        elif DATE_PREFIX.match(stripped):
            categories["ISO-like date-time or suffix"] += 1
            timestamp_values += 1
            timezone_values += int(bool(TZ_SUFFIX.search(stripped)))
        else:
            categories["other text format"] += 1
        day = date_calendar_key(value)
        if day is None:
            invalid_dates += 1
        else:
            calendar_dates.append(day)
        lossless_dates.append(date_lossless_key(value))
    return {
        "record_count": len(values),
        "raw_unique_date_strings": len(set(values)),
        "lossless_normalized_unique_date_values": len(set(lossless_dates)),
        "calendar_date_unique_values": len(set(calendar_dates)),
        "format_counts": dict(sorted(categories.items())),
        "leading_or_trailing_whitespace_records": leading_or_trailing,
        "date_time_records": timestamp_values,
        "timezone_tagged_records": timezone_values,
        "unparseable_calendar_dates": invalid_dates,
        "date_conversion_effect_note": "Calendar-date keys intentionally use the source-local calendar date; timezone conversion is not applied before assigning an ISO week.",
    }


def date_effect_rows(dataset: str, rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    result = []
    for subset in SUBSETS:
        selected = subset_rows(rows, subset)
        raw_keys = ((r["date"], canonical_decimal(r["lon"]), canonical_decimal(r["lat"])) for r in selected)
        lossless_keys = (decimal_key(r, "lossless") for r in selected)
        calendar_keys = (decimal_key(r, "calendar") for r in selected)
        for method, keys in (
            ("Raw date text plus exact decimal coordinates", raw_keys),
            ("Lossless normalized date-time plus exact decimal coordinates", lossless_keys),
            ("Source-local calendar date plus exact decimal coordinates", calendar_keys),
        ):
            result.append(metric_row(
                dataset, subset, "Date representation effect: " + method,
                "date,Decimal(lon),Decimal(lat)", keys,
            ))
    return result


def overlap_summary(updated: list[dict[str, str]], historical: list[dict[str, str]]) -> dict[str, Any]:
    def training_counter(rows: list[dict[str, str]], include_host: bool = False) -> Counter[tuple[str, ...]]:
        selected = [row for row in rows if temporal_subset(row["date"]) == "Original W16 training horizon"]
        if include_host:
            return Counter(
                (date_calendar_key(row["date"]) or "", canonical_decimal(row["lon"]),
                 canonical_decimal(row["lat"]), row["host"])
                for row in selected
            )
        return Counter(decimal_key(row, "calendar") for row in selected)

    updated_keys = training_counter(updated)
    historical_keys = training_counter(historical)
    common = set(updated_keys) & set(historical_keys)
    return {
        "temporal_scope": "2025-W01 through 2026-W16",
        "key": "source-local calendar date plus exact Decimal longitude and latitude; host excluded",
        "unique_keys_in_both_releases": len(common),
        "matched_key_multiplicity": sum(min(updated_keys[key], historical_keys[key]) for key in common),
        "updated_only_multiplicity": sum(max(0, count - historical_keys[key]) for key, count in updated_keys.items()),
        "historical_only_multiplicity": sum(max(0, count - updated_keys[key]) for key, count in historical_keys.items()),
        "exact_full_record_overlap_multiplicity": sum(
            min(updated_full[key], historical_full[key])
            for updated_full, historical_full in [(training_counter(updated, True), training_counter(historical, True))]
            for key in set(updated_full) & set(historical_full)
        ),
        "interpretation": "Cross-release overlap is reported separately and is not counted as within-dataset duplication.",
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fields: Sequence[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run(updated_path: Path, historical_path: Path, output_dir: Path) -> dict[str, Any]:
    updated, updated_header, updated_meta = read_source(updated_path, UPDATED_SHA256)
    historical, historical_header, historical_meta = read_source(historical_path, HISTORICAL_SHA256)
    summary: list[dict[str, Any]] = []
    precision: list[dict[str, Any]] = []
    rounding: list[dict[str, Any]] = []
    date_effects: list[dict[str, Any]] = []
    prior_method_meta: dict[str, Any] | None = None
    for label, rows, header, path in (
        ("Updated 2026-11-13", updated, updated_header, updated_path),
        ("Frozen W16 source 2027-07-31", historical, historical_header, historical_path),
    ):
        summary.extend(source_metric_rows(label, rows, header))
        prior_rows, prior_method_meta = pandas_previous_reconstruction(path, label)
        summary.extend(prior_rows)
        precision.extend(coordinate_precision_rows(label, rows))
        rounding.extend(rounding_rows(label, rows))
        date_effects.extend(date_effect_rows(label, rows))
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_fields = (
        "Dataset", "Temporal subset", "Comparison method", "Key columns", "Total rows",
        "Unique keys", "Duplicate groups", "Rows in duplicate groups", "Redundant rows",
        "Maximum multiplicity",
    )
    precision_fields = (
        "Dataset", "Coordinate", "Decimal places as written", "Record count",
        "Minimum decimal places", "Maximum decimal places", "Records with trailing fractional zeros",
        "Scientific notation records", "Unique textual values", "Unique exact decimal values",
        "Exact values with multiple textual forms", "Rows using those multiple forms",
        "Distinct exact values collapsed into float64 bins",
    )
    rounding_fields = (
        "Dataset", "Temporal subset", "Rounding decimal places", "Total rows", "Unique keys",
        "Duplicate groups", "Rows in duplicate groups", "Redundant rows", "Maximum multiplicity",
        "Exact decimal reference unique keys", "Additional duplicate groups vs exact reference",
        "Additional redundant rows vs exact reference", "Rounding rule",
    )
    date_fields = summary_fields
    write_csv(output_dir / "observation_duplicate_precision_summary.csv", summary, summary_fields)
    write_csv(output_dir / "observation_coordinate_precision_summary.csv", precision, precision_fields)
    write_csv(output_dir / "observation_rounding_sensitivity.csv", rounding, rounding_fields)
    write_csv(output_dir / "observation_date_normalization_summary.csv", date_effects, date_fields)
    by_name = {label: rows for label, rows in (
        ("Updated 2026-11-13", updated), ("Frozen W16 source 2027-07-31", historical)
    )}
    manifest = {
        "audit_version": "1.0.0",
        "audit_status": "COMPLETE",
        "source_integrity": {
            "updated": updated_meta,
            "historical": historical_meta,
            "checksum_gate": "Both authoritative source checksums matched before parsing or comparison."
        },
        "comparison_methodology": {
            "initial_parser": "Python csv.DictReader; UTF-8-sig; every source field remains a string.",
            "raw_character_key": "(date,lon,lat), compared exactly as stored.",
            "exact_decimal_key": "Decimal strings canonicalized by integer digits and base-10 exponent; no context rounding or coordinate precision reduction.",
            "float64_key": "Python float conversion from raw coordinate strings; date remains raw unless the method explicitly says otherwise.",
            "complete_record_key": "Every source column, raw character representation.",
            "previous_audit_reconstruction": prior_method_meta,
            "previous_audit_code_recovered_verbatim": False,
            "no_spatial_processing": True,
            "no_source_mutation": True,
            "record_level_output_written": False,
            "count_definitions": {
                "duplicate_groups": "Number of distinct keys with multiplicity k greater than 1.",
                "rows_in_duplicate_groups": "Sum of k across groups with k greater than 1.",
                "redundant_rows": "Sum of k-1 across duplicate groups.",
                "maximum_multiplicity": "Largest k among duplicate groups, or 1 when none exist."
            }
        },
        "date_audit": {
            "updated": date_audit(by_name["Updated 2026-11-13"]),
            "historical": date_audit(by_name["Frozen W16 source 2027-07-31"]),
            "normalization_comparisons": date_effects
        },
        "historical_release_overlap": overlap_summary(updated, historical),
        "output_files": [
            "observation_duplicate_precision_summary.csv",
            "observation_coordinate_precision_summary.csv",
            "observation_rounding_sensitivity.csv",
            "observation_date_normalization_summary.csv"
        ],
        "privacy": "The manifest contains aggregate metadata only; no coordinates, source rows, or record-level diagnostics are emitted."
    }
    (output_dir / "observation_duplicate_audit_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--updated-csv", required=True, type=Path)
    parser.add_argument("--historical-csv", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    manifest = run(args.updated_csv, args.historical_csv, args.output_dir)
    print(json.dumps({
        "audit_status": manifest["audit_status"],
        "updated_rows": manifest["source_integrity"]["updated"]["row_count"],
        "historical_rows": manifest["source_integrity"]["historical"]["row_count"],
        "output_files": manifest["output_files"],
        "record_level_output_written": False,
    }, separators=(",", ":")))


if __name__ == "__main__":
    main()
