#!/usr/bin/env python3
"""Fail-closed checks for pushing PTR main to a private GitHub repository."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any


MAX_GITHUB_FILE_BYTES = 50 * 1024 * 1024
ARCHIVE_SUFFIXES = (".tar", ".tar.gz", ".tar.xz", ".tgz", ".zip", ".7z")
CREDENTIAL_NAMES = {
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    ".netrc", "credentials", "credentials.json",
}
CREDENTIAL_SUFFIXES = (".pem", ".p12", ".pfx")


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, stderr=subprocess.STDOUT
    ).strip()


def load_safety_scan(root: Path):
    path = root / "scripts" / "repository_safety_scan.py"
    spec = importlib.util.spec_from_file_location("repository_safety_scan_for_github", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("repository_safety_scan_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def is_credential_path(path: str) -> bool:
    name = Path(path).name.lower()
    return name in CREDENTIAL_NAMES or name.endswith(CREDENTIAL_SUFFIXES)


def run(root: Path, *, allow_dirty: bool = False) -> dict[str, Any]:
    root = root.resolve()
    blocking: list[str] = []
    try:
        inside = git(root, "rev-parse", "--is-inside-work-tree") == "true"
        commit = git(root, "rev-parse", "HEAD")
        branch = git(root, "branch", "--show-current") or "detached"
        dirty = bool(git(root, "status", "--porcelain"))
        # Git may C-quote non-ASCII paths under a runner locale. Disable that
        # representation so Path() receives the actual checked-out filename.
        tracked = git(root, "-c", "core.quotePath=false", "ls-files").splitlines()
    except (OSError, subprocess.CalledProcessError) as exc:
        return {
            "schema_version": "github.private-preflight.v1",
            "ready_for_private_push": False,
            "blocking_reasons": [f"git_check_failed:{type(exc).__name__}"],
        }

    if not inside:
        blocking.append("not_a_git_worktree")
    if dirty and not allow_dirty:
        blocking.append("git_worktree_dirty")

    tracked_archives = [path for path in tracked if path.lower().endswith(ARCHIVE_SUFFIXES)]
    credential_paths = [path for path in tracked if is_credential_path(path)]
    oversized: list[dict[str, Any]] = []
    for path in tracked:
        candidate = root / path
        try:
            size = candidate.stat().st_size
        except OSError:
            blocking.append(f"tracked_file_unreadable:{path}")
            continue
        if size > MAX_GITHUB_FILE_BYTES:
            oversized.append({"path": path, "size_bytes": size})

    if tracked_archives:
        blocking.append("tracked_archives_present")
    if credential_paths:
        blocking.append("credential_named_files_present")
    if oversized:
        blocking.append("tracked_file_exceeds_50_mib")

    safety = load_safety_scan(root).run(root)
    sensitive_count = sum(len(paths) for paths in safety["findings"].values())
    remotes = git(root, "remote").splitlines()
    report = {
        "schema_version": "github.private-preflight.v1",
        "repository_root": str(root),
        "commit": commit,
        "branch": branch,
        "git_clean": not dirty,
        "tracked_file_count": len(tracked),
        "tracked_archives": tracked_archives,
        "credential_named_files": credential_paths,
        "oversized_files": oversized,
        "configured_remotes": remotes,
        "sensitive_candidate_count": sensitive_count,
        "private_only_required": safety["publication_blocking"],
        "ready_for_public_push": not blocking and not safety["publication_blocking"],
        "ready_for_private_push": not blocking,
        "push_scope": "main_only",
        "blocking_reasons": blocking,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Used only by CI while the checkout may contain generated build files.",
    )
    args = parser.parse_args()
    report = run(args.root, allow_dirty=args.allow_dirty)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if report.get("ready_for_private_push") else 2


if __name__ == "__main__":
    raise SystemExit(main())
