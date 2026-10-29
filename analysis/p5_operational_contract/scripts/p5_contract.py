"""Standard-library operational contract helpers for P5.

This module deliberately has no scientific-runtime dependencies.  It is used
by the production wrapper and by the failure-mode tests so that input
validation remains available even when the managed Atlas environment does not
provide pytest.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


MODEL_ID = "STRUCTURED_A3"
MODEL_SHA256 = "8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e"
P4_SUPPORT_CLASSES = ("SUPPORTED", "CAUTION", "EXTRAPOLATIVE")
FRESHNESS_STATES = ("CURRENT", "STALE_ALLOWED", "STALE_BLOCKING", "MISSING", "FUTURE_DATED", "UNKNOWN_VINTAGE")
TERMINAL_STATES = (
    "PRODUCTION_RUN_COMPLETE",
    "PRODUCTION_RUN_COMPLETE_WITH_WARNINGS",
    "PRODUCTION_RUN_BLOCKED",
    "PRODUCTION_RUN_FAILED",
)


class P5ContractError(RuntimeError):
    """A deterministic, machine-readable P5 contract failure."""

    def __init__(self, code: str, message: str):
        self.code = str(code)
        self.message = str(message)
        super().__init__(f"{self.code}: {self.message}")


def fail(code: str, message: str) -> None:
    raise P5ContractError(code, message)


def parse_iso_week(value: str) -> tuple[int, int]:
    text = str(value)
    try:
        year_text, week_text = text.split("-W", 1)
        year, week = int(year_text), int(week_text)
        date.fromisocalendar(year, week, 1)
    except (ValueError, TypeError) as exc:
        fail("INVALID_ISSUE_WEEK", f"invalid ISO week: {value!r}")
        raise AssertionError("unreachable") from exc
    return year, week


def week_start(value: str) -> date:
    year, week = parse_iso_week(value)
    return date.fromisocalendar(year, week, 1)


def issue_timestamp(value: str) -> datetime:
    """Issue at Monday 00:00 UTC immediately after the completed issue week."""
    return datetime.combine(week_start(value) + timedelta(days=7), datetime.min.time(), tzinfo=timezone.utc)


def target_week(issue_week_value: str, horizon: int) -> str:
    if int(horizon) not in (1, 2, 3):
        fail("INVALID_HORIZON", f"horizon must be 1, 2, or 3: {horizon!r}")
    target = week_start(issue_week_value) + timedelta(days=7 * int(horizon))
    iso = target.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def parse_timestamp(value: Any) -> datetime | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        fail("INVALID_SOURCE_TIMESTAMP", f"timestamp is not ISO-8601: {value!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def freshness_status(
    source_timestamp: Any,
    issue_timestamp_value: Any,
    availability_class: str,
    stale_after_days: int | None = None,
) -> str:
    """Return the only permitted freshness state for one declared source."""
    if source_timestamp is None or str(source_timestamp).strip() == "":
        return "UNKNOWN_VINTAGE"
    source = parse_timestamp(source_timestamp)
    issue = parse_timestamp(issue_timestamp_value)
    if source is None or issue is None:
        return "UNKNOWN_VINTAGE"
    if source > issue:
        return "FUTURE_DATED"
    if str(availability_class) == "RETROSPECTIVE_ONLY":
        return "STALE_BLOCKING"
    if stale_after_days is not None and (issue - source).total_seconds() > int(stale_after_days) * 86400:
        return "STALE_BLOCKING"
    if str(availability_class) == "AVAILABLE_WITH_KNOWN_LAG":
        return "STALE_ALLOWED"
    return "CURRENT"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_hash(path: Path, expected: str) -> None:
    path = Path(path)
    if not path.exists():
        fail("MISSING_REQUIRED_INPUT", f"required artifact is missing: {path}")
    actual = sha256_file(path)
    if actual != str(expected):
        fail("MODEL_HASH_MISMATCH", f"SHA-256 mismatch for {path}: expected {expected}, observed {actual}")


def validate_required_files(paths: Iterable[Path], code: str = "MISSING_REQUIRED_INPUT") -> None:
    missing = [str(Path(path)) for path in paths if not Path(path).exists()]
    if missing:
        fail(code, "missing required input(s): " + "; ".join(missing))


def validate_predictor_schema(feature_order: Iterable[str], expected: Iterable[str]) -> None:
    observed = list(feature_order)
    required = list(expected)
    if observed != required:
        fail("PREDICTOR_SCHEMA_MISMATCH", f"expected frozen predictor order of length {len(required)}, observed {len(observed)}")


def validate_spatial_contract(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    for field in ("node_count", "row_count", "column_count", "canonical_mask", "cell_order"):
        if field not in actual or field not in expected or actual[field] != expected[field]:
            fail("SPATIAL_CONTRACT_FAILED", f"spatial field {field!r} does not match the canonical contract")
    for field in ("crs", "resolution", "extent"):
        if field not in actual or field not in expected or actual[field] != expected[field]:
            fail("SPATIAL_CONTRACT_FAILED", f"spatial field {field!r} does not match the canonical contract")


def validate_target_rows(issue_week_value: str, target_rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    parse_iso_week(issue_week_value)
    rows = [dict(row) for row in target_rows]
    keys: set[tuple[str, int]] = set()
    expected: list[dict[str, Any]] = []
    for row in rows:
        horizon = int(row.get("horizon", -1))
        target = str(row.get("target_week", ""))
        parse_iso_week(target)
        key = (target, horizon)
        if key in keys:
            fail("DUPLICATE_TARGET_WEEK", f"duplicate target week/horizon: {key}")
        keys.add(key)
        if target != target_week(issue_week_value, horizon):
            fail("TARGET_WEEK_CONTRACT_FAILED", f"target {target} is inconsistent with issue {issue_week_value} and h={horizon}")
        expected.append(row)
    return expected


def validate_manifest_fields(manifest: Mapping[str, Any], required: Iterable[str]) -> None:
    missing = [field for field in required if field not in manifest or manifest[field] in (None, "")]
    if missing:
        fail("MISSING_PROVENANCE_METADATA", "manifest is missing required field(s): " + ", ".join(missing))


def validate_support_class(value: str) -> None:
    if str(value) not in P4_SUPPORT_CLASSES:
        fail("SUPPORT_REFERENCE_INVALID", f"unsupported P4 support class: {value!r}")


def warning_flags(support_class: str, uncertainty_available: bool, input_states: Iterable[str]) -> list[str]:
    validate_support_class(support_class)
    flags: list[str] = []
    if support_class == "CAUTION":
        flags.append("CAUTION_SUPPORT")
    elif support_class == "EXTRAPOLATIVE":
        flags.append("EXTRAPOLATIVE_SUPPORT")
    if not uncertainty_available:
        flags.append("PARTIAL_UNCERTAINTY")
    for state in input_states:
        if state == "STALE_BLOCKING":
            flags.append("STALE_INPUT")
        elif state == "FUTURE_DATED":
            flags.append("FUTURE_DATED_INPUT")
        elif state == "UNKNOWN_VINTAGE":
            flags.append("UNKNOWN_VINTAGE")
    return list(dict.fromkeys(flags))


def highest_warning(flags: Iterable[str]) -> str:
    ordered = (
        "INPUT_VALIDATION_FAILED",
        "PRODUCTION_BLOCKED",
        "FUTURE_DATED_INPUT",
        "STALE_INPUT",
        "UNKNOWN_VINTAGE",
        "EXTRAPOLATIVE_SUPPORT",
        "CAUTION_SUPPORT",
        "PARTIAL_UNCERTAINTY",
        "OK",
    )
    values = set(flags)
    return next((item for item in ordered if item in values), "OK")


def jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    return value


def output_schema() -> list[dict[str, str]]:
    return [
        {"name": "canonical_node_id", "type": "integer", "required": "true"},
        {"name": "model_node_id", "type": "integer", "required": "true"},
        {"name": "target_week", "type": "ISO-week", "required": "true"},
        {"name": "horizon", "type": "integer", "required": "true"},
        {"name": "p_occurrence", "type": "float", "required": "true"},
        {"name": "conditional_count_mean", "type": "float", "required": "true"},
        {"name": "expected_count", "type": "float", "required": "true"},
        {"name": "full_q025", "type": "float-or-null", "required": "true"},
        {"name": "full_q975", "type": "float-or-null", "required": "true"},
        {"name": "p_boot_sd", "type": "float-or-null", "required": "true"},
        {"name": "expected_boot_sd", "type": "float-or-null", "required": "true"},
        {"name": "novelty_knn_distance", "type": "float", "required": "true"},
        {"name": "support_class", "type": "enum:SUPPORTED|CAUTION|EXTRAPOLATIVE", "required": "true"},
        {"name": "warning_status", "type": "enum", "required": "true"},
        {"name": "warning_flags", "type": "semicolon-delimited-enum", "required": "true"},
    ]
