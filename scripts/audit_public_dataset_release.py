#!/usr/bin/env python3
"""Audit public MedCAT-Silver repo for private artifacts and row-level leaks."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]

ALLOWED_PUBLIC_JSONL_FILES = {"examples/synthetic_text_concept_dataset.jsonl"}
ALLOWED_MARKER_OCCURRENCES = {
    ("scripts/audit_public_dataset_release.py", "/home/"),
    ("scripts/audit_public_dataset_release.py", "/restricted"),
    ("scripts/audit_public_dataset_release.py", "\"sample_rows\""),
    ("scripts/audit_public_dataset_release.py", "synthetic sensitive row"),
    ("scripts/audit_public_dataset_release.py", "private-note-id"),
    ("scripts/build_medcat_silver_dataset.py", "\"sample_rows\""),
    ("tests/medcat_silver_dataset_test.py", "synthetic sensitive row"),
    ("tests/test_make_medcat_silver_public_manifest.py", "/restricted"),
    ("tests/test_make_medcat_silver_public_manifest.py", "\"sample_rows\""),
    ("tests/test_make_medcat_silver_public_manifest.py", "synthetic sensitive row"),
    ("tests/test_make_medcat_silver_public_manifest.py", "private-note-id"),
    ("tests/test_audit_public_dataset_release.py", "/home/"),
    ("tests/test_audit_public_dataset_release.py", "/restricted"),
    ("tests/test_audit_public_dataset_release.py", "\"sample_rows\""),
    ("tests/test_audit_public_dataset_release.py", "synthetic sensitive row"),
    ("tests/test_audit_public_dataset_release.py", "private-note-id"),
}

FORBIDDEN_JSONL_BASENAMES = {"text_concept_dataset.jsonl"}
FORBIDDEN_FILENAMES = {"summary.json"}
FORBIDDEN_BINARY_EXTENSIONS = {
    ".bin",
    ".ckpt",
    ".h5",
    ".npz",
    ".npy",
    ".onnx",
    ".pkl",
    ".pt",
    ".pth",
    ".safetensors",
}
FORBIDDEN_PATH_COMPONENT_MARKERS = {"medcat_omop_snomed_condition_cdb", "model-pack", "model_pack", ".cdb"}
PRIVATE_TEXT_PATTERNS = [
    ("/home/", lambda text: "/home/" in text),
    ("/restricted", lambda text: "/restricted" in text),
    (
        "\"sample_rows\"",
        lambda text: re.search(r"\"sample_rows\"\s*:", text) is not None,
    ),
    ("synthetic sensitive row", lambda text: "synthetic sensitive row" in text),
    ("private-note-id", lambda text: "private-note-id" in text),
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_root", nargs="?", default=str(ROOT), help="Repository root to audit.")
    parser.add_argument(
        "--check-staged",
        action="store_true",
        help="Also inspect staged git paths for private artifacts.",
    )
    return parser.parse_args(argv)


def _iter_files(root: Path) -> Iterable[Path]:
    skip_parts = {".git", ".venv", ".pytest_cache", ".ruff_cache", "__pycache__"}
    for candidate in root.rglob("*"):
        if not candidate.is_file():
            continue
        if candidate.is_symlink():
            continue
        rel = candidate.relative_to(root).as_posix()
        if rel.startswith(".git/") or any(part in skip_parts for part in candidate.relative_to(root).parts):
            continue
        yield candidate


def _rel(root: Path, target: Path) -> str:
    return target.relative_to(root).as_posix()


def _is_text_path(path: Path) -> bool:
    text_extensions = {
        ".csv",
        ".gitignore",
        ".json",
        ".jsonl",
        ".md",
        ".py",
        ".sh",
        ".toml",
        ".txt",
        ".yaml",
        ".yml",
    }
    return (
        path.suffix.lower() in text_extensions
        or path.name in {".gitignore"}
        or path.suffix == ""
    )


def _private_path_violation(path: Path, rel: str) -> str | None:
    parts = [part.lower() for part in rel.split("/")]

    if "data" in parts:
        return "private dataset directory detected"

    if path.name in FORBIDDEN_FILENAMES:
        return f"private file name '{path.name}' is forbidden"

    if path.name in FORBIDDEN_JSONL_BASENAMES:
        return f"private JSONL file '{path.name}' is forbidden"

    if path.suffix.lower() == ".jsonl" and rel not in ALLOWED_PUBLIC_JSONL_FILES:
        return "private JSONL artifact outside public example allowlist"

    if path.suffix.lower() in FORBIDDEN_BINARY_EXTENSIONS:
        return f"private binary model artifact '{path.name}' ({path.suffix})"

    for part in parts:
        if any(marker in part for marker in FORBIDDEN_PATH_COMPONENT_MARKERS):
            return f"private MedCAT CDB/model-pack path detected in '{part}'"

    return None


def _private_text_markers_violation(relative_path: str, text: str) -> str | None:
    lowered = text.lower()
    for marker, test in PRIVATE_TEXT_PATTERNS:
        if (relative_path, marker) in ALLOWED_MARKER_OCCURRENCES:
            continue
        if test(lowered):
            return f"private marker '{marker}' in text file"
    return None


def collect_public_dataset_release_violations(repo_root: Path) -> list[str]:
    repo_root = repo_root.resolve()
    violations: list[str] = []

    for path in _iter_files(repo_root):
        rel = _rel(repo_root, path)

        path_violation = _private_path_violation(path, rel)
        if path_violation:
            violations.append(f"{rel}: {path_violation}")
            continue

        if _is_text_path(path):
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            marker_violation = _private_text_markers_violation(rel, text)
            if marker_violation:
                violations.append(f"{rel}: {marker_violation}")

    return sorted(violations)


def _normalize_staged_paths(lines: str) -> list[str]:
    return [line.strip() for line in lines.splitlines() if line.strip()]


def _get_staged_paths(repo_root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "diff", "--cached", "--name-only"],
            check=False,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError:
        return []

    if result.returncode != 0:
        return []

    return _normalize_staged_paths(result.stdout)


def check_staged_private_artifacts(
    repo_root: Path,
    staged_paths: list[str] | None = None,
) -> list[str]:
    staged_paths = _get_staged_paths(repo_root) if staged_paths is None else staged_paths
    staged_root = repo_root.resolve()
    violations: list[str] = []
    for staged_path in staged_paths:
        rel = staged_path.replace("\\", "/").lstrip("/")
        abs_path = staged_root / rel
        path_violation = _private_path_violation(abs_path, rel)
        if path_violation:
            violations.append(f"{rel}: {path_violation}")
    return sorted(set(violations))


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).resolve()

    violations = collect_public_dataset_release_violations(repo_root)
    if args.check_staged:
        violations.extend(check_staged_private_artifacts(repo_root))
        violations = sorted(set(violations))

    if violations:
        for violation in violations:
            print(violation, file=sys.stderr)
        sys.exit(1)

    print("Public MedCAT release checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
