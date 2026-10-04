#!/usr/bin/env python3
"""Dependency-light contract checks for completed Task 3E outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("/project/disease_ecology/STGNN-output/v2_rasters"),
    )
    args = parser.parse_args()
    root = args.output_root
    manifest = json.loads((root / "manifests/task3e_raster_manifest.json").read_text())
    qa = json.loads((root / "qa/task3e_raster_qa.json").read_text())
    assert manifest["model_id"] == "STGNN-Hurdle-V2A"
    assert manifest["branch"] == "feature/v2-raster-outputs"
    assert manifest["qa_passed"] is True
    assert qa["all_checks_pass"] is True
    assert qa["node_count"] == 10037
    assert qa["canonical_revised_domain_cell_count"] == 10037
    assert qa["pseudo_nowcast_rasters_exclude_outcomes"] is True
    assert len(manifest["weeks_rendered"]) == 13
    assert len(manifest["tif_paths"]) == 43
    assert len(manifest["figure_paths"]) == 4

    checksum_path = root / "manifests/task3e_checksums.csv"
    rows = checksum_path.read_text().splitlines()
    assert len(rows) == 48
    for line in rows[1:]:
        relative_path, _, expected = line.split(",", 2)
        relative_path = relative_path.strip('"')
        expected = expected.strip().strip('"')
        path = root / relative_path
        assert path.exists(), path
        assert sha256_file(path) == expected, path
    print(json.dumps({"status": "passed", "checksum_rows": len(rows) - 1}, indent=2))


if __name__ == "__main__":
    main()
