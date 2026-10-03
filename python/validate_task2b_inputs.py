from __future__ import annotations

import hashlib
import json
from pathlib import Path


def main() -> None:
    output = Path("/project/disease_ecology/STGNN-output")
    model = output / "model_data"
    manifest = json.loads((model / "manifests/dataset_manifest.json").read_text())
    mismatches = []
    for name, expected in manifest["raw_artifact_checksums"].items():
        digest = hashlib.sha256((model / "raw" / name).read_bytes()).hexdigest()
        if digest != expected:
            mismatches.append({"name": name, "expected": expected, "observed": digest})
    if mismatches:
        raise SystemExit(json.dumps({"all_match": False, "mismatches": mismatches}, indent=2))
    print(json.dumps({"all_match": True, "checked": len(manifest["raw_artifact_checksums"]), "git_sha": manifest["git_sha"], "shapes": manifest["array_shapes"]}, indent=2))


if __name__ == "__main__":
    main()
