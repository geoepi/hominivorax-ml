"""Byte-level regression guard for the immutable frozen A3 manifest."""

from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "analysis" / "structured_a3_evaluation" / "results" / "frozen_a3_evaluation_manifest.json"
SIDECAR = MANIFEST.with_name(MANIFEST.name + ".sha256")
EXPECTED_SHA256 = "9d7bc7b9ce41263064104aa933e75771b2b918ed853e4e34145db83c3a2c8f61"


class FrozenManifestIntegrityTests(unittest.TestCase):
    def test_immutable_manifest_bytes_match_declared_sha256(self) -> None:
        sidecar_text = SIDECAR.read_text(encoding="utf-8")
        match = re.match(r"^([0-9a-f]{64})\s+", sidecar_text.strip(), flags=re.IGNORECASE)
        self.assertIsNotNone(match, "frozen manifest sidecar is not a SHA-256 declaration")
        declared = match.group(1).lower()
        self.assertEqual(declared, EXPECTED_SHA256)
        observed = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
        self.assertEqual(observed, EXPECTED_SHA256)


if __name__ == "__main__":
    unittest.main()
