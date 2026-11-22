"""Stable full-fit artifact inventory with external master-manifest checksums."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any


CSV_NAME = "structured_a3_fullfit_output_manifest.csv"
JSON_NAME = "structured_a3_fullfit_output_manifest.json"
CSV_SIDECAR_NAME = f"{CSV_NAME}.sha256"
JSON_SIDECAR_NAME = f"{JSON_NAME}.sha256"
FIELDS = (
    "artifact_type", "week", "variable", "path", "relative_path", "sha256",
    "size_bytes", "model_sha", "fit_end_week",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact_type(relative_path: str) -> str:
    suffix = Path(relative_path).suffix.lower()
    if suffix in {".tif", ".tiff"}:
        return "geotiff"
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".png", ".svg"}:
        return "figure"
    if suffix in {".csv", ".parquet"}:
        return "table"
    if suffix in {".md", ".html"}:
        return "report"
    if "/model/" in f"/{relative_path}":
        return "model_artifact"
    return "manifest"


def _is_inventory_input(path: Path, root: Path) -> bool:
    relative = path.relative_to(root).as_posix()
    parts = relative.split("/")
    if parts[0] == "logs":
        return False
    if path.name in {CSV_NAME, JSON_NAME, CSV_SIDECAR_NAME, JSON_SIDECAR_NAME}:
        return False
    if any(part.startswith(".") for part in parts):
        return False
    if path.suffix.lower() in {".tmp", ".part"} or path.name.endswith(".sha256"):
        return False
    return True


def collect_records(root: Path, model_sha: str, fit_end_week: str) -> list[dict[str, Any]]:
    """Collect stable non-log products, excluding master inventory files."""
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"full-fit output root is not a directory: {root}")
    records = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not _is_inventory_input(path, root):
            continue
        relative = path.relative_to(root).as_posix()
        records.append({
            "artifact_type": artifact_type(relative),
            "week": "",
            "variable": "",
            "path": str(path),
            "relative_path": relative,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
            "model_sha": model_sha,
            "fit_end_week": fit_end_week,
        })
    return records


def _atomic_write(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_master_manifests(root: Path, records: list[dict[str, Any]], model_sha: str) -> dict[str, Any]:
    """Write the CSV inventory once, then JSON and external checksum sidecars."""
    root = root.resolve(strict=True)
    csv_path = root / CSV_NAME
    json_path = root / JSON_NAME
    from io import StringIO

    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, extrasaction="raise", lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    csv_bytes = buffer.getvalue().encode("utf-8")
    _atomic_write(csv_path, csv_bytes)
    csv_sha = hashlib.sha256(csv_bytes).hexdigest()

    payload = {
        "status": "complete",
        "artifact_count": len(records),
        "manifest_file": CSV_NAME,
        "manifest_sha256": csv_sha,
        "model_sha256": model_sha,
        "logs_included": False,
        "master_manifests_included": False,
    }
    json_bytes = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write(json_path, json_bytes)
    json_sha = hashlib.sha256(json_bytes).hexdigest()
    _atomic_write(root / CSV_SIDECAR_NAME, f"{csv_sha}  {CSV_NAME}\n".encode("utf-8"))
    _atomic_write(root / JSON_SIDECAR_NAME, f"{json_sha}  {JSON_NAME}\n".encode("utf-8"))
    return {**payload, "json_sha256": json_sha}
