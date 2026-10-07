"""Check tracked repository files against public-release hygiene limits."""

from __future__ import annotations

import subprocess
from pathlib import Path


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


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    problems = check_paths(repo_root, tracked_paths(repo_root))
    if problems:
        print("Repository hygiene check failed:")
        print("\n".join(f"- {problem}" for problem in problems))
        return 1
    print(
        "Repository hygiene check passed: tracked files are <= 5 MiB and contain "
        "no prohibited production-data extensions."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
