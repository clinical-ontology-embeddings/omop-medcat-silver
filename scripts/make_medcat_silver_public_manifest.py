#!/usr/bin/env python3
"""Create a GitHub-safe manifest for the MedCAT silver dataset recipe.

The private generation summary contains local paths and sample rows with
MIMIC-derived sentence text. This script emits only aggregate counts and
regeneration metadata that can be committed to a public repository.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


DATASET_NAME = "omop-medcat-silver-full-v1"
NOTE_INPUT_PATH = "data/01_raw/mimic-iv-note/2.2/note/discharge.csv.gz"
VOCAB_INPUT_PATH = "data/01_raw/vocabulary_v5"
CDB_PATH = "data/03_processed/text_concept_dataset/medcat_silver_v1/medcat_omop_snomed_condition_cdb"
OUTPUT_DATASET_PATH = "data/03_processed/text_concept_dataset/medcat_silver_full_v1/text_concept_dataset.jsonl"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--summary-json",
        default="data/03_processed/text_concept_dataset/medcat_silver_full_v1/reports/summary.json",
        help="Private MedCAT silver generation summary.json.",
    )
    parser.add_argument(
        "--out",
        default="docs/dataset/medcat_silver_full_v1_public_manifest.json",
        help="GitHub-safe output manifest path.",
    )
    return parser.parse_args(argv)


def build_public_manifest(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Return a public manifest that excludes row-level clinical content."""
    return {
        "dataset_name": DATASET_NAME,
        "release_type": "regeneration_recipe_only",
        "public_distribution": {
            "dataset_jsonl": "not_included",
            "medcat_cdb": "not_included",
            "reason": (
                "The generated JSONL contains MIMIC-derived sentence text, note IDs, "
                "subject IDs, admission IDs, and mention offsets. Public GitHub "
                "distribution is limited to code, documentation, and aggregate metadata."
            ),
        },
        "required_inputs": [
            {
                "name": "MIMIC-IV-Note discharge notes",
                "path": NOTE_INPUT_PATH,
                "access": "PhysioNet credentialed access required; not redistributed by this repository.",
            },
            {
                "name": "OMOP vocabulary v5",
                "path": VOCAB_INPUT_PATH,
                "access": "Local OHDSI/OMOP vocabulary download required; not redistributed by this repository.",
            },
        ],
        "regeneration_command": [
            "python3",
            "scripts/build_medcat_silver_dataset.py",
            "--note-file",
            NOTE_INPUT_PATH,
            "--out-root",
            "data/03_processed/text_concept_dataset/medcat_silver_full_v1",
            "--cdb-path",
            CDB_PATH,
            "--max-notes",
            "0",
            "--min-sentence-words",
            str(summary.get("min_sentence_words", 6)),
            "--max-sentences-per-note",
            str(summary.get("max_sentences_per_note", 20)),
        ],
        "expected_output": {
            "path": OUTPUT_DATASET_PATH,
            "schema": {
                "unit": "sentence_or_short_clinical_statement",
                "positive_labels": "OMOP SNOMED Condition concept_ids for present mentions",
                "hard_negative_labels": "negated mention concept_ids retained for diagnostics/training",
                "row_level_fields_not_public": [
                    "note_id",
                    "subject_id",
                    "hadm_id",
                    "text",
                    "mentions",
                    "hard_negative_mentions",
                ],
            },
        },
        "output_statistics": {
            "label_source": summary.get("label_source"),
            "note_scope": summary.get("note_scope"),
            "medcat_version": summary.get("medcat_version"),
            "source_notes": summary.get("source_notes"),
            "notes_with_mentions": summary.get("notes_with_mentions"),
            "skipped_no_sentence_mentions": summary.get("skipped_no_sentence_mentions"),
            "written_rows": summary.get("written_rows"),
            "unique_concepts": summary.get("unique_concepts"),
            "unique_hard_negative_concepts": summary.get("unique_hard_negative_concepts"),
            "label_count_histogram": summary.get("label_count_histogram", {}),
            "mention_confidence_histogram": summary.get("mention_confidence_histogram", {}),
            "top_concepts": summary.get("top_concepts", []),
            "top_hard_negative_concepts": summary.get("top_hard_negative_concepts", []),
            "vocabulary_filter": summary.get("vocabulary_filter"),
            "max_notes": summary.get("max_notes"),
            "include_negated": summary.get("include_negated"),
        },
        "public_safety_checks": [
            "Do not commit text_concept_dataset.jsonl.",
            "Do not commit private generation summary files containing example rows.",
            "Do not commit MedCAT CDB/model-pack files built from restricted vocabularies.",
            "Run the focused tests before publishing recipe changes.",
        ],
        "official_source_references": [
            "https://physionet.org/content/mimic-iv-note/",
            "https://www.physionet.org/content/mimiciv/1.0/",
            "https://physionet.org/content/mimiciv/view-dua/1.0/",
        ],
    }


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    summary_path = Path(args.summary_json)
    output_path = Path(args.out)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest = build_public_manifest(summary)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
