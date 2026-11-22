"""Check tracked repository files against public-release hygiene limits."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote


MAX_TRACKED_FILE_BYTES = 5 * 1024 * 1024
PROHIBITED_SUFFIXES = (
    ".parquet",
    ".feather",
    ".arrow",
    ".tif",
    ".tiff",
    ".vrt",
    ".nc",
    ".npy",
    ".npz",
    ".rds",
    ".rdata",
    ".h5",
    ".hdf5",
    ".gpkg",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".fst",
    ".grib",
    ".grib2",
    ".zarr",
    ".zip",
    ".7z",
    ".tar",
    ".tar.gz",
    ".csv.gz",
)


def tracked_paths(repo_root: Path) -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={repo_root.as_posix()}",
            "-C",
            str(repo_root),
            "ls-files",
            "-z",
        ],
        check=True,
        capture_output=True,
    )
    return [
        repo_root / raw.decode("utf-8")
        for raw in result.stdout.split(b"\0")
        if raw
    ]


def is_fixture(path: Path, repo_root: Path) -> bool:
    relative = path.relative_to(repo_root).as_posix()
    return relative == "tests/fixtures" or relative.startswith("tests/fixtures/")


def check_paths(repo_root: Path, paths: list[Path]) -> list[str]:
    problems: list[str] = []
    for path in paths:
        relative = path.relative_to(repo_root).as_posix()
        if not path.exists():
            problems.append(f"tracked path is missing from the checkout: {relative}")
            continue
        size = path.stat().st_size
        if size > MAX_TRACKED_FILE_BYTES:
            problems.append(
                f"tracked file exceeds 5 MiB ({size} bytes): {relative}"
            )
        lower_name = path.name.lower()
        if not is_fixture(path, repo_root) and any(
            lower_name.endswith(suffix) for suffix in PROHIBITED_SUFFIXES
        ):
            problems.append(f"prohibited production-data extension: {relative}")
    return problems


def check_json_syntax(paths: list[Path]) -> list[str]:
    problems: list[str] = []
    for path in paths:
        if path.suffix.lower() != ".json":
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            problems.append(f"invalid JSON: {path.as_posix()} ({error})")
    return problems


def check_yaml_syntax(repo_root: Path, paths: list[Path]) -> list[str]:
    yaml_paths = [path for path in paths if path.suffix.lower() in {".yaml", ".yml"}]
    if not yaml_paths:
        return []
    ruby = shutil.which("ruby")
    if ruby is None:
        return ["YAML syntax check requires Ruby's standard-library Psych parser"]
    result = subprocess.run(
        [ruby, "-e", "require 'yaml'; ARGV.each { |path| YAML.parse_file(path) }",
         *[path.relative_to(repo_root).as_posix() for path in yaml_paths]],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        return [f"invalid YAML syntax: {detail or 'Ruby YAML parser failed'}"]
    return []


MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\((<[^>]+>|[^)\s]+)(?:\s+[^)]*)?\)")
FENCED_CODE = re.compile(r"```.*?```|~~~.*?~~~", flags=re.DOTALL)
EXTERNAL_SCHEMES = ("http://", "https://", "mailto:", "data:", "tel:")


def check_markdown_links(repo_root: Path, paths: list[Path]) -> list[str]:
    problems: list[str] = []
    for path in paths:
        if path.suffix.lower() != ".md":
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            problems.append(f"could not read Markdown: {path.as_posix()} ({error})")
            continue
        content = FENCED_CODE.sub("", content)
        for match in MARKDOWN_LINK.finditer(content):
            target = match.group(1).strip("<>")
            if not target or target.startswith(EXTERNAL_SCHEMES) or target.startswith("#"):
                continue
            target_path = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if not target_path:
                continue
            resolved = (repo_root / target_path.lstrip("/")) if target_path.startswith("/") else path.parent / target_path
            if not resolved.exists():
                problems.append(
                    f"broken Markdown link in {path.relative_to(repo_root).as_posix()}: {target}"
                )
    return problems


def check_freeze_manifest(repo_root: Path) -> list[str]:
    manifest_path = repo_root / "config" / "production_model_freeze.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return [f"could not validate scientific freeze manifest: {error}"]

    problems: list[str] = []
    for artifact in manifest.get("frozen_artifacts", []):
        relative = artifact.get("path")
        expected = artifact.get("sha256")
        if not relative or not expected:
            problems.append("scientific freeze manifest has an artifact without path or SHA-256")
            continue
        artifact_path = (repo_root / relative).resolve()
        if not artifact_path.is_relative_to(repo_root.resolve()):
            problems.append(f"scientific freeze artifact escapes the repository: {relative}")
            continue
        if not artifact_path.is_file():
            problems.append(f"scientific freeze artifact is missing: {relative}")
            continue
        actual = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if actual.lower() != str(expected).lower():
            problems.append(f"scientific freeze artifact checksum mismatch: {relative}")
    return problems


def check_status_source(repo_root: Path, paths: list[Path]) -> list[str]:
    status_path = repo_root / "docs" / "current" / "status.md"
    readme_path = repo_root / "README.md"
    model_status_path = repo_root / "MODEL_STATUS.md"
    problems: list[str] = []
    for path in (status_path, readme_path, model_status_path):
        if not path.is_file():
            problems.append(f"canonical current-status document or link source is missing: {path.relative_to(repo_root)}")
    if problems:
        return problems
    status = status_path.read_text(encoding="utf-8")
    if "CANDIDATE_READY_FOR_REVIEW_NOT_PRODUCTION_QUALIFIED" not in status:
        problems.append("canonical status does not identify the W44 candidate qualification state")
    declarations = 0
    for path in paths:
        if path.suffix.lower() == ".md" and "docs/current" in path.relative_to(repo_root).as_posix():
            declarations += len(re.findall(r"(?im)^\*\*Candidate status:\*\*", path.read_text(encoding="utf-8")))
    if declarations != 1:
        problems.append(f"current documentation must have one canonical candidate-status declaration (found {declarations})")
    for path in (readme_path, model_status_path):
        if "docs/current/status.md" not in path.read_text(encoding="utf-8"):
            problems.append(f"top-level status entry point does not link to docs/current/status.md: {path.name}")
    return problems


def check_branch_inventory(repo_root: Path) -> list[str]:
    inventory = repo_root / "docs" / "repository_maintenance" / "branch_inventory.csv"
    if not inventory.is_file():
        return ["repository-maintenance branch inventory is missing"]
    try:
        with inventory.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {"branch", "head_sha", "canonical_compare_ref", "classification", "files_changed"}
            missing = required.difference(reader.fieldnames or [])
            if missing:
                return [f"branch inventory is missing columns: {', '.join(sorted(missing))}"]
            branches = [row["branch"] for row in reader]
    except (OSError, UnicodeError, csv.Error) as error:
        return [f"invalid branch inventory CSV: {error}"]
    if len(branches) != len(set(branches)):
        return ["branch inventory contains duplicate branch rows"]
    return []


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    paths = tracked_paths(repo_root)
    problems = check_paths(repo_root, paths)
    problems.extend(check_json_syntax(paths))
    problems.extend(check_yaml_syntax(repo_root, paths))
    problems.extend(check_markdown_links(repo_root, paths))
    problems.extend(check_freeze_manifest(repo_root))
    problems.extend(check_status_source(repo_root, paths))
    problems.extend(check_branch_inventory(repo_root))
    if problems:
        print("Repository hygiene check failed:")
        print("\n".join(f"- {problem}" for problem in problems))
        return 1
    print(
        "Repository checks passed: tracked files are <= 5 MiB; prohibited "
        "production-data extensions are absent; internal Markdown links, JSON/YAML, "
        "scientific freeze checksums, current-status links, and branch inventory are valid."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
