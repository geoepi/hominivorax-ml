"""Synthetic integrity checks for deterministic full-fit master manifests."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis" / "structured_a3_fullfit" / "scripts"))
from output_manifest import (  # noqa: E402
    CSV_NAME,
    CSV_SIDECAR_NAME,
    JSON_NAME,
    JSON_SIDECAR_NAME,
    collect_records,
    write_master_manifests,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FullfitOutputManifestTests(unittest.TestCase):
    def test_inventory_excludes_live_logs_and_master_manifests_and_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model/fullfit_a3_model.json"
            report = root / "report/summary.md"
            log = root / "logs/fullfit_123.out"
            model.parent.mkdir(parents=True)
            report.parent.mkdir(parents=True)
            log.parent.mkdir(parents=True)
            model.write_text('{"model":"fixture"}\n', encoding="utf-8")
            report.write_text("synthetic report\n", encoding="utf-8")
            log.write_text("slurm output may continue to grow\n", encoding="utf-8")

            records = collect_records(root, "model-sha", "2026-W44")
            relatives = {item["relative_path"] for item in records}
            self.assertEqual(relatives, {"model/fullfit_a3_model.json", "report/summary.md"})
            first = write_master_manifests(root, records, "model-sha")
            csv_path, json_path = root / CSV_NAME, root / JSON_NAME
            self.assertEqual(first["manifest_sha256"], sha(csv_path))
            self.assertEqual((root / CSV_SIDECAR_NAME).read_text().split()[0], sha(csv_path))
            self.assertEqual((root / JSON_SIDECAR_NAME).read_text().split()[0], sha(json_path))
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["manifest_sha256"], sha(csv_path))
            self.assertFalse(payload["logs_included"])
            self.assertFalse(payload["master_manifests_included"])
            with csv_path.open(newline="", encoding="utf-8") as handle:
                csv_rows = list(csv.DictReader(handle))
            self.assertEqual({row["relative_path"] for row in csv_rows}, relatives)

            log.write_text("slurm output changed after finalization\n", encoding="utf-8")
            repeated = write_master_manifests(root, collect_records(root, "model-sha", "2026-W44"), "model-sha")
            self.assertEqual(first["manifest_sha256"], repeated["manifest_sha256"])
            self.assertEqual(first["json_sha256"], repeated["json_sha256"])


if __name__ == "__main__":
    unittest.main()
