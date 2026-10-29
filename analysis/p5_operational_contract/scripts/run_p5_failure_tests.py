#!/usr/bin/env python3
"""Run standard-library P5 deliberate failure tests.

The managed Atlas Python environment does not contain pytest.  These tests
exercise the contract validators directly and write a machine-readable result
for every required failure mode.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile

from p5_contract import (
    P5ContractError,
    fail,
    freshness_status,
    validate_manifest_fields,
    validate_predictor_schema,
    validate_required_files,
    validate_spatial_contract,
    validate_target_rows,
    verify_hash,
)


def expect_failure(name: str, expected_code: str, action) -> dict[str, str]:
    try:
        action()
    except P5ContractError as exc:
        return {"test": name, "expected_code": expected_code, "observed_code": exc.code, "status": "PASS" if exc.code == expected_code else "FAIL", "message": exc.message}
    except Exception as exc:  # pragma: no cover - defensive contract reporting
        return {"test": name, "expected_code": expected_code, "observed_code": type(exc).__name__, "status": "FAIL", "message": str(exc)}
    return {"test": name, "expected_code": expected_code, "observed_code": "NO_FAILURE", "status": "FAIL", "message": "validator accepted an invalid input"}


def run(output: Path) -> list[dict[str, str]]:
    output.mkdir(parents=True, exist_ok=True)
    issue = "2026-10-05T00:00:00Z"
    future = "2026-10-12T00:00:00Z"
    stale = "2026-08-01T00:00:00Z"
    expected_spatial = {
        "node_count": 10037,
        "row_count": "canonical_mask",
        "column_count": "canonical_mask",
        "canonical_mask": "canonical 10,037-node revised domain",
        "cell_order": "model_node_id 0..10036",
        "crs": "EPSG:4326 node coordinates with frozen 25 x 25 km canonical cells",
        "resolution": "25 x 25 km canonical cells",
        "extent": "canonical model_node_id 0 through 10036 in revised-domain order",
    }
    with tempfile.TemporaryDirectory(prefix="p5-failure-tests-") as temporary:
        temporary_path = Path(temporary)
        present = temporary_path / "present.bin"
        present.write_bytes(b"canonical")
        results = [
            expect_failure("missing predictor file", "MISSING_REQUIRED_INPUT", lambda: validate_required_files([temporary_path / "missing.npy"])),
            expect_failure("stale predictor", "STALE_BLOCKING", lambda: _raise_freshness(freshness_status(stale, issue, "AVAILABLE_WITH_KNOWN_LAG", stale_after_days=7), "STALE_BLOCKING")),
            expect_failure("future-dated predictor", "FUTURE_DATED", lambda: _raise_freshness(freshness_status(future, issue, "AVAILABLE_AS_OF_ISSUE"), "FUTURE_DATED")),
            expect_failure("wrong CRS", "SPATIAL_CONTRACT_FAILED", lambda: validate_spatial_contract({**expected_spatial, "crs": "EPSG:3857"}, expected_spatial)),
            expect_failure("wrong resolution", "SPATIAL_CONTRACT_FAILED", lambda: validate_spatial_contract({**expected_spatial, "resolution": "10 x 10 km"}, expected_spatial)),
            expect_failure("wrong extent", "SPATIAL_CONTRACT_FAILED", lambda: validate_spatial_contract({**expected_spatial, "extent": "wrong extent"}, expected_spatial)),
            expect_failure("predictor-schema mismatch", "PREDICTOR_SCHEMA_MISMATCH", lambda: validate_predictor_schema(["a"], ["a", "b"])),
            expect_failure("corrupted model artifact/hash mismatch", "MODEL_HASH_MISMATCH", lambda: verify_hash(present, "0" * 64)),
            expect_failure("missing support-reference artifact", "MISSING_SUPPORT_REFERENCE", lambda: validate_required_files([temporary_path / "missing-support.parquet"], code="MISSING_SUPPORT_REFERENCE")),
            expect_failure("duplicate target week", "DUPLICATE_TARGET_WEEK", lambda: validate_target_rows("2026-W40", [{"target_week": "2026-W41", "horizon": 1}, {"target_week": "2026-W41", "horizon": 1}])),
            expect_failure("invalid issue week", "INVALID_ISSUE_WEEK", lambda: validate_target_rows("2026-W99", [])),
            expect_failure("partial predictor coverage", "MISSING_REQUIRED_INPUT", lambda: validate_required_files([present, temporary_path / "partial-missing.parquet"])),
            expect_failure("missing provenance metadata", "MISSING_PROVENANCE_METADATA", lambda: validate_manifest_fields({"run_id": "only"}, ["run_id", "model_sha256", "input_manifest_sha256"])),
        ]
    with (output / "failure_mode_test_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["test", "expected_code", "observed_code", "status", "message"])
        writer.writeheader()
        writer.writerows(results)
    summary = {"status": "PASS" if all(row["status"] == "PASS" for row in results) else "FAIL", "tests": len(results), "passed": sum(row["status"] == "PASS" for row in results), "failed": sum(row["status"] != "PASS" for row in results), "results": results}
    (output / "failure_mode_test_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return results


def _raise_freshness(observed: str, expected: str) -> None:
    if observed != expected:
        fail("FRESHNESS_RULE_FAILED", f"expected {expected}, observed {observed}")
    fail(observed, "deliberate invalid freshness state")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = run(args.output)
    print(json.dumps({"status": "PASS" if all(row["status"] == "PASS" for row in results) else "FAIL", "tests": len(results)}, indent=2))
    return 0 if all(row["status"] == "PASS" for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
