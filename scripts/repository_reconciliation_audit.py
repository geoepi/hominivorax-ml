#!/usr/bin/env python3
"""Generate reproducible Git branch inventory and relationship tables.

This helper is intentionally limited to repository metadata.  It does not
read model inputs, protected data, or generated model outputs.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
from pathlib import Path


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={repo.as_posix()}", *args],
        cwd=repo,
        text=True,
    ).strip()


def worktrees(repo: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    current: str | None = None
    for line in git(repo, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            current = line.removeprefix("worktree ")
        elif line.startswith("branch refs/heads/") and current is not None:
            result[line.removeprefix("branch refs/heads/")] = current
    return result


def refs(repo: Path) -> list[dict[str, str]]:
    fmt = "%(refname:short)|%(objectname)|%(upstream:short)|%(committerdate:iso-strict)|%(subject)"
    rows: list[dict[str, str]] = []
    for line in git(repo, "for-each-ref", f"--format={fmt}", "refs/heads", "refs/remotes").splitlines():
        name, sha, upstream, date, subject = line.split("|", 4)
        if name == "origin" or name.endswith("/HEAD"):
            continue
        is_local = not name.startswith("origin/")
        rows.append({
            "branch": name if is_local else name.removeprefix("origin/"),
            "local_or_remote": "local" if is_local else "remote",
            "ref": name,
            "tip_sha": sha,
            "tracking_branch": upstream,
            "last_commit_date": date,
            "last_commit_subject": subject,
        })
    return rows


def inventory(repo: Path, output: Path) -> None:
    wt = worktrees(repo)
    rows = []
    for row in refs(repo):
        ref = row["ref"]
        row = dict(row)
        row.update({
            "merge_base_with_main": git(repo, "merge-base", "main", ref),
            "commits_ahead_of_main": git(repo, "rev-list", "--count", f"main..{ref}"),
            "commits_behind_main": git(repo, "rev-list", "--count", f"{ref}..main"),
            "worktree": wt.get(row["branch"], ""),
        })
        row.pop("ref")
        rows.append(row)
    fields = [
        "branch", "local_or_remote", "tip_sha", "merge_base_with_main",
        "commits_ahead_of_main", "commits_behind_main", "tracking_branch",
        "worktree", "last_commit_date", "last_commit_subject",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def relationships(repo: Path, output: Path) -> None:
    ref_rows = refs(repo)
    counts: dict[str, int] = {}
    for row in ref_rows:
        counts[row["branch"]] = counts.get(row["branch"], 0) + 1
    rows = []
    for item in ref_rows:
        branch = item["branch"]
        ref = item["ref"]
        tip = git(repo, "rev-parse", ref)
        base = git(repo, "merge-base", "main", ref)
        ahead = int(git(repo, "rev-list", "--count", f"main..{ref}"))
        behind = int(git(repo, "rev-list", "--count", f"{ref}..main"))
        rows.append({
            "branch": branch,
            "local_or_remote": item["local_or_remote"],
            "ref": ref,
            "tip_sha": tip,
            "merge_base_with_main": base,
            "commits_ahead_of_main": ahead,
            "commits_behind_main": behind,
            "fully_merged_into_main": "YES" if ahead == 0 else "NO",
            "tip_reachable_from_main": "YES" if ahead == 0 else "NO",
            "shared_with_local_or_remote": "YES" if counts[branch] > 1 else "NO",
            "notes": "See branch_relationships.md for scientific ancestry and supersession interpretation.",
        })
    fields = list(rows[0]) if rows else ["branch"]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path("docs/repository_reconciliation"))
    args = parser.parse_args()
    repo = args.repo.resolve()
    inventory(repo, args.output_dir / "branch_inventory.csv")
    relationships(repo, args.output_dir / "branch_relationships.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
