import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.make_medcat_silver_public_manifest import build_public_manifest, main


def _private_summary():
    return {
        "label_source": "medcat_omop_snomed_condition",
        "note_scope": "discharge",
        "note_file": "/restricted/project/data/01_raw/mimic-iv-note/2.2/note/discharge.csv.gz",
        "dataset_path": "/restricted/project/data/03_processed/text_concept_dataset/medcat_silver_full_v1/text_concept_dataset.jsonl",
        "medcat_version": "2.7.0",
        "min_sentence_words": 6,
        "max_sentences_per_note": 20,
        "max_notes": 0,
        "include_negated": False,
        "source_notes": 331793,
        "notes_with_mentions": 331792,
        "skipped_no_sentence_mentions": 1,
        "written_rows": 2266848,
        "unique_concepts": 11629,
        "unique_hard_negative_concepts": 3725,
        "label_count_histogram": {"1": 1300297, "2": 527827},
        "mention_confidence_histogram": {"1.0-1.1": 4575824},
        "top_concepts": [{"concept_id": 4329041, "mention_count": 281792}],
        "top_hard_negative_concepts": [{"concept_id": 433595, "mention_count": 1000}],
        "sample_rows": [
            {
                "note_id": "private-note-id",
                "subject_id": 123,
                "hadm_id": 456,
                "text": "synthetic sensitive row must not be public",
            }
        ],
        "vocabulary_filter": "domain_id=Condition; vocabulary_id=SNOMED",
    }


def test_build_public_manifest_strips_row_level_content_and_absolute_paths():
    manifest = build_public_manifest(_private_summary())

    serialized = json.dumps(manifest, ensure_ascii=False)
    assert "sample_rows" not in serialized
    assert "synthetic sensitive row" not in serialized
    assert "private-note-id" not in serialized
    assert "/restricted" not in serialized
    assert "".join(["HO", "VE"]) not in serialized
    assert "".join(["ho", "ve"]) not in serialized
    assert manifest["public_distribution"]["dataset_jsonl"] == "not_included"
    assert manifest["dataset_name"] == "omop-medcat-silver-full-v1"
    assert manifest["required_inputs"][0]["path"] == "data/01_raw/mimic-iv-note/2.2/note/discharge.csv.gz"
    assert manifest["expected_output"]["path"] == (
        "data/03_processed/text_concept_dataset/medcat_silver_full_v1/text_concept_dataset.jsonl"
    )
    assert manifest["output_statistics"]["written_rows"] == 2266848


def test_cli_writes_public_manifest_without_sensitive_summary_fields(tmp_path):
    summary_path = tmp_path / "summary.json"
    output_path = tmp_path / "public_manifest.json"
    summary_path.write_text(json.dumps(_private_summary()), encoding="utf-8")

    main(["--summary-json", str(summary_path), "--out", str(output_path)])

    payload = output_path.read_text(encoding="utf-8")
    assert "synthetic sensitive row" not in payload
    assert "sample_rows" not in payload
    manifest = json.loads(payload)
    assert manifest["dataset_name"] == "omop-medcat-silver-full-v1"
