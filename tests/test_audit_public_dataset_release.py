from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.audit_public_dataset_release import (
    check_staged_private_artifacts,
    collect_public_dataset_release_violations,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _allowed_public_manifest(path: Path) -> None:
    _write(
        path,
        """{
  "dataset_name": "omop-medcat-silver-full-v1"
}
""",
    )


def test_collect_violations_passes_clean_layout(tmp_path: Path):
    _write(tmp_path / "README.md", "# Test dataset release")
    _write(tmp_path / "docs/dataset/medcat_silver_full_v1_public_manifest.json", "{}")
    (tmp_path / "scripts").mkdir(exist_ok=True)

    assert collect_public_dataset_release_violations(tmp_path) == []


def test_repository_declares_public_dependencies():
    requirements = Path(__file__).resolve().parents[1] / "requirements.txt"
    lines = {
        line.strip()
        for line in requirements.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    assert "medcat==2.7.0" in lines
    assert "pytest==9.0.3" in lines
    assert "spacy==3.8.14" in lines
    assert "numpy==2.1.2" in lines
    assert "pandas==2.3.3" in lines
    assert "scikit-learn==1.7.2" in lines
    assert "torch==2.10.0" in lines
    assert "transformers==5.5.4" in lines
    assert "sentence-transformers==5.1.2" in lines


def test_repository_readme_has_professional_public_dataset_structure():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")

    assert "# OMOP MedCAT Silver" in readme
    assert "## At a Glance" in readme
    assert "## Repository Layout" in readme
    assert "## Requirements" in readme
    assert "## Quick Start" in readme
    assert "## Release Boundary" in readme
    assert "## License and External Terms" in readme
    assert "https://opensource.org/license/mit" in readme
    assert "https://physionet.org/content/mimic-iv-note/" in readme
    assert "https://physionet.org/content/mimiciv/view-dua/1.0/" in readme
    assert "https://www.ohdsi.org/data-standardization/the-common-data-model/" in readme
    assert "https://athena.ohdsi.org/" in readme
    assert "https://github.com/CogStack/MedCAT" in readme


def test_repository_readme_shows_synthetic_example_row_inline():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")

    assert "Single synthetic sample" in readme
    assert "```json" in readme
    assert '"note_id": "example-note-001"' in readme
    assert '"text": "Synthetic example sentence reports pneumonia and no edema today."' in readme
    assert '"hard_negative_mentions": [' in readme
    assert "example-note-002" not in readme


def test_repository_includes_synthetic_example_rows():
    example_path = Path(__file__).resolve().parents[1] / "examples/synthetic_text_concept_dataset.jsonl"

    rows = [
        json.loads(line)
        for line in example_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert len(rows) >= 2
    for row in rows:
        assert set(row) == {
            "note_id",
            "subject_id",
            "hadm_id",
            "sentence_index",
            "text",
            "concept_ids",
            "concept_names",
            "hard_negative_concept_ids",
            "hard_negative_concept_names",
            "mentions",
            "hard_negative_mentions",
            "label_source",
        }
        assert row["note_id"].startswith("example-note-")
        assert row["subject_id"].startswith("example-subject-")
        assert row["hadm_id"].startswith("example-encounter-")
        assert row["text"].startswith("Synthetic example sentence")
        assert isinstance(row["concept_ids"], list)
        assert isinstance(row["concept_names"], list)
        assert isinstance(row["mentions"], list)
        assert isinstance(row["hard_negative_mentions"], list)
        assert row["label_source"] == "medcat_omop_snomed_condition"


def test_collect_violations_allows_synthetic_example_jsonl(tmp_path: Path):
    _allowed_public_manifest(tmp_path / "docs/dataset/medcat_silver_full_v1_public_manifest.json")
    _write(
        tmp_path / "examples/synthetic_text_concept_dataset.jsonl",
        """{"note_id":"example-note-001","subject_id":"example-subject-001","hadm_id":"example-encounter-001","sentence_index":0,"text":"Synthetic example sentence only.","concept_ids":[],"concept_names":[],"hard_negative_concept_ids":[],"hard_negative_concept_names":[],"mentions":[],"hard_negative_mentions":[],"label_source":"medcat_omop_snomed_condition"}\n""",
    )

    assert collect_public_dataset_release_violations(tmp_path) == []


def test_collect_violations_flags_private_jsonl(tmp_path: Path):
    _allowed_public_manifest(tmp_path / "docs/dataset/medcat_silver_full_v1_public_manifest.json")
    _write(tmp_path / "data/03_processed/text_concept_dataset/medcat_silver_full_v1/text_concept_dataset.jsonl", "bad")

    violations = collect_public_dataset_release_violations(tmp_path)
    assert any("text_concept_dataset.jsonl" in v for v in violations)


def test_collect_violations_flags_private_summary(tmp_path: Path):
    _allowed_public_manifest(tmp_path / "docs/dataset/medcat_silver_full_v1_public_manifest.json")
    _write(tmp_path / "data/03_processed/text_concept_dataset/medcat_silver_full_v1/reports/summary.json", "{}")

    violations = collect_public_dataset_release_violations(tmp_path)
    assert any("summary.json" in v for v in violations)


def test_collect_violations_flags_private_markers_in_public_manifest(tmp_path: Path):
    _write(
        tmp_path / "docs/dataset/medcat_silver_full_v1_public_manifest.json",
        """{
  "dataset_name": "omop-medcat-silver-full-v1",
  "sample_rows": []
}
""",
    )

    violations = collect_public_dataset_release_violations(tmp_path)
    assert any("sample_rows" in v for v in violations)


def test_collect_violations_flags_private_marker_in_readme(tmp_path: Path):
    _write(
        tmp_path / "README.md",
        """# Test\n/private\n/restricted/project data path should fail.\n"""
    )
    _write(
        tmp_path / "docs/dataset/medcat_silver_full_v1_public_manifest.json",
        "{}",
    )

    violations = collect_public_dataset_release_violations(tmp_path)
    assert any("/restricted" in v for v in violations)


def test_check_staged_private_artifacts_reports_private_rows():
    staged = [
        "data/03_processed/text_concept_dataset/medcat_silver_full_v1/text_concept_dataset.jsonl",
        "docs/dataset/medcat_silver_full_v1_public_manifest.json",
    ]
    violations = check_staged_private_artifacts(Path.cwd(), staged)
    assert any("text_concept_dataset.jsonl" in v for v in violations)


def test_check_staged_private_artifacts_allows_synthetic_example_rows():
    staged = ["examples/synthetic_text_concept_dataset.jsonl"]

    assert check_staged_private_artifacts(Path.cwd(), staged) == []
