import csv
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.build_medcat_silver_dataset import (
    MedcatMention,
    build_medcat_silver_dataset,
    extract_omop_snomed_condition_aliases,
    sentence_spans,
)


def _write_omop_vocab(root: Path) -> None:
    root.mkdir()
    with (root / "CONCEPT.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "concept_id",
                "concept_name",
                "domain_id",
                "vocabulary_id",
                "standard_concept",
                "invalid_reason",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "concept_id": "111",
                "concept_name": "Pneumonia",
                "domain_id": "Condition",
                "vocabulary_id": "SNOMED",
                "standard_concept": "S",
                "invalid_reason": "",
            }
        )
        writer.writerow(
            {
                "concept_id": "222",
                "concept_name": "Serum sodium measurement",
                "domain_id": "Measurement",
                "vocabulary_id": "SNOMED",
                "standard_concept": "S",
                "invalid_reason": "",
            }
        )
        writer.writerow(
            {
                "concept_id": "333",
                "concept_name": "Old condition",
                "domain_id": "Condition",
                "vocabulary_id": "SNOMED",
                "standard_concept": "S",
                "invalid_reason": "D",
            }
        )
    with (root / "CONCEPT_SYNONYM.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["concept_id", "concept_synonym_name", "language_concept_id"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "concept_id": "111",
                "concept_synonym_name": "Lung infection",
                "language_concept_id": "4180186",
            }
        )
        writer.writerow(
            {
                "concept_id": "111",
                "concept_synonym_name": "neumonía",
                "language_concept_id": "4182511",
            }
        )
        writer.writerow(
            {
                "concept_id": "222",
                "concept_synonym_name": "Sodium",
                "language_concept_id": "4180186",
            }
        )


def _write_discharge(path: Path) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "note_id",
                "subject_id",
                "hadm_id",
                "note_type",
                "note_seq",
                "charttime",
                "storetime",
                "text",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "note_id": "n1",
                "subject_id": "10",
                "hadm_id": "100",
                "note_type": "DS",
                "note_seq": "1",
                "charttime": "2026-01-01 00:00:00",
                "storetime": "",
                "text": "The patient was treated for pneumonia. No sepsis was present.",
            }
        )


def test_extract_omop_snomed_condition_aliases_filters_to_valid_standard_conditions(tmp_path):
    vocab = tmp_path / "vocab"
    _write_omop_vocab(vocab)

    aliases = extract_omop_snomed_condition_aliases(vocab)

    assert aliases == [
        {"concept_id": 111, "concept_name": "Pneumonia", "alias": "Lung infection"},
        {"concept_id": 111, "concept_name": "Pneumonia", "alias": "Pneumonia"},
    ]


def test_extract_omop_aliases_handles_large_synonym_fields(tmp_path):
    vocab = tmp_path / "vocab"
    _write_omop_vocab(vocab)
    with (vocab / "CONCEPT_SYNONYM.csv").open("a", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["concept_id", "concept_synonym_name", "language_concept_id"],
        )
        writer.writerow(
            {
                "concept_id": "111",
                "concept_synonym_name": "p" * 140000,
                "language_concept_id": "4180186",
            }
        )

    aliases = extract_omop_snomed_condition_aliases(vocab)

    assert any(alias["alias"] == "p" * 140000 for alias in aliases)


def test_sentence_spans_map_offsets_to_full_sentences():
    text = "The patient was treated for pneumonia. No sepsis was present."

    spans = sentence_spans(text, min_words=3, max_sentences=0)

    assert spans == [
        (0, 38, "The patient was treated for pneumonia."),
        (39, 61, "No sepsis was present."),
    ]


def test_sentence_spans_preserve_original_offsets_after_wrapped_lines():
    text = (
        " \n"
        "History:\n"
        "The patient had abdominal pain and  \n"
        "worsening distension. She denies edema and dyspnea."
    )

    spans = sentence_spans(text, min_words=3, max_sentences=0)

    assert spans == [
        (
            text.index("The patient"),
            text.index("worsening distension.") + len("worsening distension."),
            "The patient had abdominal pain and worsening distension.",
        ),
        (
            text.index("She denies"),
            text.index("dyspnea.") + len("dyspnea."),
            "She denies edema and dyspnea.",
        ),
    ]


def test_sentence_spans_split_inline_physical_exam_labels():
    text = (
        "================= ADMISSION/DISCHARGE EXAM ================= "
        "VS: 97.9 109/71 GEN: Thin anxious woman, no acute distress "
        "ABD: Soft, non-tender, non-distended EXTREM: no edema"
    )

    spans = sentence_spans(text, min_words=2, max_sentences=0)

    assert spans == [
        (
            text.index("97.9"),
            text.index("GEN:") - 1,
            "97.9 109/71",
        ),
        (
            text.index("Thin"),
            text.index("ABD:") - 1,
            "Thin anxious woman, no acute distress",
        ),
        (
            text.index("Soft"),
            text.index("EXTREM:") - 1,
            "Soft, non-tender, non-distended",
        ),
        (
            text.index("no edema"),
            len(text),
            "no edema",
        ),
    ]


def test_sentence_spans_split_inline_ros_labels_with_short_labels():
    text = (
        "GEN: +fever and chills HEENT: denies sore throat or congestion "
        "CV: no chest pain or edema RESP: no cough GI: +abdominal pain over bladder"
    )

    spans = sentence_spans(text, min_words=2, max_sentences=0)

    assert [span[2] for span in spans] == [
        "+fever and chills",
        "denies sore throat or congestion",
        "no chest pain or edema",
        "no cough",
        "+abdominal pain over bladder",
    ]


def test_sentence_spans_split_multiline_physical_exam_labels():
    text = (
        "================= ADMISSION/DISCHARGE EXAM =================\n"
        "VS: 97.9 PO 109 / 71 70 16 97 ra\n"
        "GEN: Thin anxious woman, lying in bed, no acute distress\n"
        "HEENT: Moist MM, anicteric sclerae\n"
        "EXTREM: Warm, well-perfused, no edema\n"
    )

    spans = sentence_spans(text, min_words=2, max_sentences=0)

    assert [span[2] for span in spans] == [
        "97.9 PO 109 / 71 70 16 97 ra",
        "Thin anxious woman, lying in bed, no acute distress",
        "Moist MM, anicteric sclerae",
        "Warm, well-perfused, no edema",
    ]


def test_build_medcat_silver_dataset_maps_mentions_to_sentences_and_keeps_negated_hard_negatives(tmp_path):
    note_file = tmp_path / "discharge.csv"
    out_root = tmp_path / "silver"
    _write_discharge(note_file)

    def fake_annotator(text: str):
        return [
            MedcatMention(
                start=text.index("pneumonia"),
                end=text.index("pneumonia") + len("pneumonia"),
                text="pneumonia",
                concept_id=111,
                concept_name="Pneumonia",
                confidence=0.95,
                negated=False,
            ),
            MedcatMention(
                start=text.index("sepsis"),
                end=text.index("sepsis") + len("sepsis"),
                text="sepsis",
                concept_id=222,
                concept_name="Sepsis",
                confidence=0.91,
                negated=True,
            ),
        ]

    summary = build_medcat_silver_dataset(
        note_file=note_file,
        out_root=out_root,
        annotator=fake_annotator,
        medcat_version="fake-test",
        min_sentence_words=3,
        max_sentences_per_note=0,
    )

    rows = [
        json.loads(line)
        for line in (out_root / "text_concept_dataset.jsonl").read_text().splitlines()
    ]
    assert summary["label_source"] == "medcat_omop_snomed_condition"
    assert summary["written_rows"] == 1
    assert summary["unique_concepts"] == 1
    assert rows == [
        {
            "note_id": "n1",
            "subject_id": 10,
            "hadm_id": 100,
            "sentence_index": 0,
            "text": "The patient was treated for pneumonia.",
            "concept_ids": [111],
            "concept_names": ["Pneumonia"],
            "hard_negative_concept_ids": [],
            "hard_negative_concept_names": [],
            "mentions": [
                {
                    "start": 28,
                    "end": 37,
                    "text": "pneumonia",
                    "concept_id": 111,
                    "concept_ids": [111],
                    "concept_name": "Pneumonia",
                    "confidence": 0.95,
                    "negated": False,
                    "assertion": "present",
                }
            ],
            "hard_negative_mentions": [],
            "label_source": "medcat_omop_snomed_condition",
        }
    ]


def test_build_medcat_silver_dataset_does_not_carry_mentions_from_skipped_short_sentences(tmp_path):
    note_file = tmp_path / "discharge.csv"
    out_root = tmp_path / "silver"
    with note_file.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "note_id",
                "subject_id",
                "hadm_id",
                "note_type",
                "note_seq",
                "charttime",
                "storetime",
                "text",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "note_id": "n1",
                "subject_id": "10",
                "hadm_id": "100",
                "note_type": "DS",
                "note_seq": "1",
                "charttime": "2026-01-01 00:00:00",
                "storetime": "",
                "text": "No dysuria.  \nShe had food poisoning after dinner.",
            }
        )

    def fake_annotator(text: str):
        return [
            MedcatMention(
                start=text.index("dysuria"),
                end=text.index("dysuria") + len("dysuria"),
                text="dysuria",
                concept_id=197684,
                concept_name="Dysuria",
                confidence=1.0,
                negated=False,
            ),
            MedcatMention(
                start=text.index("food poisoning"),
                end=text.index("food poisoning") + len("food poisoning"),
                text="food poisoning",
                concept_id=434854,
                concept_name="Food poisoning",
                confidence=1.0,
                negated=False,
            ),
        ]

    build_medcat_silver_dataset(
        note_file=note_file,
        out_root=out_root,
        annotator=fake_annotator,
        medcat_version="fake-test",
        min_sentence_words=5,
        max_sentences_per_note=0,
    )

    rows = [
        json.loads(line)
        for line in (out_root / "text_concept_dataset.jsonl").read_text().splitlines()
    ]
    assert rows[0]["text"] == "She had food poisoning after dinner."
    assert rows[0]["concept_ids"] == [434854]


def test_build_medcat_silver_dataset_keeps_rule_based_negated_mentions_as_hard_negatives(tmp_path):
    note_file = tmp_path / "discharge.csv"
    out_root = tmp_path / "silver"
    with note_file.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "note_id",
                "subject_id",
                "hadm_id",
                "note_type",
                "note_seq",
                "charttime",
                "storetime",
                "text",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "note_id": "n1",
                "subject_id": "10",
                "hadm_id": "100",
                "note_type": "DS",
                "note_seq": "1",
                "charttime": "2026-01-01 00:00:00",
                "storetime": "",
                "text": "She denies edema but has pneumonia.",
            }
        )

    def fake_annotator(text: str):
        return [
            MedcatMention(
                start=text.index("edema"),
                end=text.index("edema") + len("edema"),
                text="edema",
                concept_id=433595,
                concept_name="Edema",
                confidence=1.0,
                negated=False,
            ),
            MedcatMention(
                start=text.index("pneumonia"),
                end=text.index("pneumonia") + len("pneumonia"),
                text="pneumonia",
                concept_id=111,
                concept_name="Pneumonia",
                confidence=1.0,
                negated=False,
            ),
        ]

    build_medcat_silver_dataset(
        note_file=note_file,
        out_root=out_root,
        annotator=fake_annotator,
        medcat_version="fake-test",
        min_sentence_words=3,
        max_sentences_per_note=0,
    )

    rows = [
        json.loads(line)
        for line in (out_root / "text_concept_dataset.jsonl").read_text().splitlines()
    ]
    assert rows[0]["concept_ids"] == [111]
    assert rows[0]["hard_negative_concept_ids"] == [433595]
    assert rows[0]["mentions"] == [
        {
            "start": 25,
            "end": 34,
            "text": "pneumonia",
            "concept_id": 111,
            "concept_ids": [111],
            "concept_name": "Pneumonia",
            "confidence": 1.0,
            "negated": False,
            "assertion": "present",
        }
    ]
    assert rows[0]["hard_negative_mentions"] == [
        {
            "start": 11,
            "end": 16,
            "text": "edema",
            "concept_id": 433595,
            "concept_ids": [433595],
            "concept_name": "Edema",
            "confidence": 1.0,
            "negated": True,
            "assertion": "negated",
        }
    ]


def test_build_medcat_silver_dataset_does_not_negate_distant_not_mentions(tmp_path):
    note_file = tmp_path / "discharge.csv"
    out_root = tmp_path / "silver"
    text = "Patient is not on transplant list because of comorbidities and presents with abdominal pain."
    with note_file.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "note_id",
                "subject_id",
                "hadm_id",
                "note_type",
                "note_seq",
                "charttime",
                "storetime",
                "text",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "note_id": "n1",
                "subject_id": "10",
                "hadm_id": "100",
                "note_type": "DS",
                "note_seq": "1",
                "charttime": "2026-01-01 00:00:00",
                "storetime": "",
                "text": text,
            }
        )

    def fake_annotator(note_text: str):
        return [
            MedcatMention(
                start=note_text.index("pain"),
                end=note_text.index("pain") + len("pain"),
                text="pain",
                concept_id=4329041,
                concept_name="Dolor",
                confidence=1.0,
                negated=False,
            )
        ]

    build_medcat_silver_dataset(
        note_file=note_file,
        out_root=out_root,
        annotator=fake_annotator,
        medcat_version="fake-test",
        min_sentence_words=3,
        max_sentences_per_note=0,
    )

    rows = [
        json.loads(line)
        for line in (out_root / "text_concept_dataset.jsonl").read_text().splitlines()
    ]
    assert rows[0]["concept_ids"] == [4329041]
    assert rows[0]["hard_negative_concept_ids"] == []


def test_build_medcat_silver_dataset_uses_canonical_omop_concept_names(tmp_path):
    note_file = tmp_path / "discharge.csv"
    out_root = tmp_path / "silver"
    with note_file.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "note_id",
                "subject_id",
                "hadm_id",
                "note_type",
                "note_seq",
                "charttime",
                "storetime",
                "text",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "note_id": "n1",
                "subject_id": "10",
                "hadm_id": "100",
                "note_type": "DS",
                "note_seq": "1",
                "charttime": "2026-01-01 00:00:00",
                "storetime": "",
                "text": "The patient has abdominal pain.",
            }
        )

    def fake_annotator(text: str):
        return [
            MedcatMention(
                start=text.index("pain"),
                end=text.index("pain") + len("pain"),
                text="pain",
                concept_id=4329041,
                concept_name="Dolor",
                confidence=1.0,
                negated=False,
            )
        ]

    build_medcat_silver_dataset(
        note_file=note_file,
        out_root=out_root,
        annotator=fake_annotator,
        medcat_version="fake-test",
        min_sentence_words=3,
        max_sentences_per_note=0,
        canonical_concept_names={4329041: "Pain"},
    )

    rows = [
        json.loads(line)
        for line in (out_root / "text_concept_dataset.jsonl").read_text().splitlines()
    ]
    assert rows[0]["concept_names"] == ["Pain"]
    assert rows[0]["mentions"][0]["concept_name"] == "Pain"


def test_build_medcat_silver_dataset_drops_generic_only_rows(tmp_path):
    note_file = tmp_path / "discharge.csv"
    out_root = tmp_path / "silver"
    with note_file.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "note_id",
                "subject_id",
                "hadm_id",
                "note_type",
                "note_seq",
                "charttime",
                "storetime",
                "text",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "note_id": "n1",
                "subject_id": "10",
                "hadm_id": "100",
                "note_type": "DS",
                "note_seq": "1",
                "charttime": "2026-01-01 00:00:00",
                "storetime": "",
                "text": "For HIV disease, she is being followed by Dr.",
            }
        )

    def fake_annotator(text: str):
        return [
            MedcatMention(
                start=text.index("disease"),
                end=text.index("disease") + len("disease"),
                text="disease",
                concept_id=4274025,
                concept_name="Disease",
                confidence=1.0,
                negated=False,
            )
        ]

    build_medcat_silver_dataset(
        note_file=note_file,
        out_root=out_root,
        annotator=fake_annotator,
        medcat_version="fake-test",
        min_sentence_words=3,
        max_sentences_per_note=0,
    )

    rows = [
        json.loads(line)
        for line in (out_root / "text_concept_dataset.jsonl").read_text().splitlines()
    ]
    assert rows == []


def test_build_medcat_silver_dataset_prunes_generic_pain_when_specific_pain_exists(tmp_path):
    note_file = tmp_path / "discharge.csv"
    out_root = tmp_path / "silver"
    text = "He describes right-sided chest pain."
    with note_file.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "note_id",
                "subject_id",
                "hadm_id",
                "note_type",
                "note_seq",
                "charttime",
                "storetime",
                "text",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "note_id": "n1",
                "subject_id": "10",
                "hadm_id": "100",
                "note_type": "DS",
                "note_seq": "1",
                "charttime": "2026-01-01 00:00:00",
                "storetime": "",
                "text": text,
            }
        )

    def fake_annotator(note_text: str):
        return [
            MedcatMention(
                start=note_text.index("right-sided chest pain"),
                end=note_text.index("right-sided chest pain") + len("right-sided chest pain"),
                text="right-sided chest pain",
                concept_id=4109083,
                concept_name="Right sided chest pain",
                confidence=1.0,
                negated=False,
            ),
            MedcatMention(
                start=note_text.index("pain"),
                end=note_text.index("pain") + len("pain"),
                text="pain",
                concept_id=4329041,
                concept_name="Pain",
                confidence=1.0,
                negated=False,
            ),
        ]

    build_medcat_silver_dataset(
        note_file=note_file,
        out_root=out_root,
        annotator=fake_annotator,
        medcat_version="fake-test",
        min_sentence_words=3,
        max_sentences_per_note=0,
    )

    rows = [
        json.loads(line)
        for line in (out_root / "text_concept_dataset.jsonl").read_text().splitlines()
    ]
    assert rows[0]["concept_ids"] == [4109083]
    assert rows[0]["concept_names"] == ["Right sided chest pain"]


def test_build_medcat_silver_dataset_negates_coordinated_no_list(tmp_path):
    note_file = tmp_path / "discharge.csv"
    out_root = tmp_path / "silver"
    text = "She has no abdominal pain, nausea, vomiting, chest pain, or difficulty breathing."
    with note_file.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "note_id",
                "subject_id",
                "hadm_id",
                "note_type",
                "note_seq",
                "charttime",
                "storetime",
                "text",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "note_id": "n1",
                "subject_id": "10",
                "hadm_id": "100",
                "note_type": "DS",
                "note_seq": "1",
                "charttime": "2026-01-01 00:00:00",
                "storetime": "",
                "text": text,
            }
        )

    def fake_annotator(note_text: str):
        names = [
            ("abdominal pain", 200219, "Abdominal pain"),
            ("nausea", 31967, "Nausea"),
            ("vomiting", 441408, "Emesis"),
            ("chest pain", 77670, "Chest pain"),
            ("difficulty breathing", 4041664, "DIB - Difficulty in breathing"),
        ]
        return [
            MedcatMention(
                start=note_text.index(name),
                end=note_text.index(name) + len(name),
                text=name,
                concept_id=concept_id,
                concept_name=concept_name,
                confidence=1.0,
                negated=False,
            )
            for name, concept_id, concept_name in names
        ]

    build_medcat_silver_dataset(
        note_file=note_file,
        out_root=out_root,
        annotator=fake_annotator,
        medcat_version="fake-test",
        min_sentence_words=3,
        max_sentences_per_note=0,
    )

    rows = [
        json.loads(line)
        for line in (out_root / "text_concept_dataset.jsonl").read_text().splitlines()
    ]
    assert rows == []


def test_build_medcat_silver_dataset_stops_negation_scope_at_but_has(tmp_path):
    note_file = tmp_path / "discharge.csv"
    out_root = tmp_path / "silver"
    text = "She denies edema but has pneumonia."
    with note_file.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "note_id",
                "subject_id",
                "hadm_id",
                "note_type",
                "note_seq",
                "charttime",
                "storetime",
                "text",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "note_id": "n1",
                "subject_id": "10",
                "hadm_id": "100",
                "note_type": "DS",
                "note_seq": "1",
                "charttime": "2026-01-01 00:00:00",
                "storetime": "",
                "text": text,
            }
        )

    def fake_annotator(note_text: str):
        return [
            MedcatMention(
                start=note_text.index("edema"),
                end=note_text.index("edema") + len("edema"),
                text="edema",
                concept_id=433595,
                concept_name="Edema",
                confidence=1.0,
                negated=False,
            ),
            MedcatMention(
                start=note_text.index("pneumonia"),
                end=note_text.index("pneumonia") + len("pneumonia"),
                text="pneumonia",
                concept_id=111,
                concept_name="Pneumonia",
                confidence=1.0,
                negated=False,
            ),
        ]

    build_medcat_silver_dataset(
        note_file=note_file,
        out_root=out_root,
        annotator=fake_annotator,
        medcat_version="fake-test",
        min_sentence_words=3,
        max_sentences_per_note=0,
    )

    rows = [
        json.loads(line)
        for line in (out_root / "text_concept_dataset.jsonl").read_text().splitlines()
    ]
    assert rows[0]["concept_ids"] == [111]
    assert rows[0]["hard_negative_concept_ids"] == [433595]
