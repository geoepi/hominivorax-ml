#!/usr/bin/env python3
"""Write the deterministic P7G artifact/provenance manifest."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def git_sha(root: Path) -> str:
    return subprocess.check_output(["git", "-c", f"safe.directory={root.as_posix()}", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def main() -> int:
    phase = Path(__file__).resolve().parents[1]
    repo = phase.parents[1]
    files = []
    for directory in (phase / "results", phase / "figures", phase / "config"):
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.name != "p7g_reproducibility_manifest.json":
                files.append({"path": str(path.relative_to(repo)).replace("\\", "/"), "sha256": sha256(path), "size_bytes": path.stat().st_size})
    for path in [phase / "p7g_prespecification.md", phase / "p7g_manuscript_evidence_report.md"]:
        files.append({"path": str(path.relative_to(repo)).replace("\\", "/"), "sha256": sha256(path), "size_bytes": path.stat().st_size})
    payload = {
        "phase": "P7G",
        "analysis_version": "p7g-manuscript-evidence-v1",
        "built_from_commit": git_sha(repo),
        "prespecification_commit": "cf092e888a6014f627dc7cd452963a5ffb66aeda",
        "atlas_job_id": "21069366",
        "atlas_output_root": "/project/disease_ecology/STGNN-output/p7g_manuscript_evidence_20261030_r2/",
        "frozen_model_sha256": "8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e",
        "p2_archive_sha256": "918b33e80d352c080fcefb3d7b2a44dc29d0096b0b2e7dd6f5b017becc983170",
        "p4_support_sha256": "c35bf794fcc882e3ea71bc1a279b90e4f32aeff412a9399f2fb25e383141d058",
        "no_model_fitting": True,
        "artifact_count": len(files),
        "artifacts": files,
    }
    out = phase / "results/p7g_reproducibility_manifest.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "P7G_MANIFEST_WRITTEN", "path": str(out), "artifact_count": len(files), "built_from_commit": payload["built_from_commit"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
