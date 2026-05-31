#!/usr/bin/env python3
"""Build MedCAT-derived sentence-to-OMOP silver labels from MIMIC discharge notes."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


LABEL_SOURCE = "medcat_omop_snomed_condition"
OUT_DEFAULT = Path("data/03_processed/text_concept_dataset/medcat_silver_v1")
NOTE_DEFAULT = Path("data/01_raw/mimic-iv-note/2.2/note/discharge.csv.gz")
VOCAB_DEFAULT = Path("data/01_raw/vocabulary_v5")
ENGLISH_LANGUAGE_CONCEPT_ID = "4180186"
ALWAYS_DROP_GENERIC_CONCEPT_IDS = {
    4274025,  # Disease
    443392,  # Malignant neoplastic disease
    432250,  # Infectious disease
}
OVERLAP_DROP_GENERIC_CONCEPT_IDS = {
    4329041,  # Pain
    4274025,  # Disease
    443392,  # Malignant neoplastic disease
    442562,  # Poisoning
}
ADMIN_LINE_RE = re.compile(
    r"^\s*(?:name|unit no|admission date|discharge date|date of birth|sex|service)\s*:",
    re.IGNORECASE,
)
SECTION_HEADER_RE = re.compile(r"^\s*[A-Za-z][A-Za-z0-9 /,_()&-]{1,80}:\s*$")
SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")
INLINE_CLINICAL_LABEL_RE = re.compile(r"\b[A-Z][A-Z0-9/ ]{1,14}:\s*")
CLINICAL_LINE_LABEL_RE = re.compile(
    r"^\s*(?:VS|VITALS?|TEMP|HR|BP|RR|GEN|GENERAL|HEENT|NECK|PULM|RESP|"
    r"CV|COR|CARDIAC|LUNGS?|ABD|ABDOMEN|GI|GU|MSK|EXT|EXTREM|NEURO|SKIN|"
    r"LIMBS?)\s*:\s*",
    re.IGNORECASE,
)
DECORATIVE_HEADER_RE = re.compile(r"^\s*=+\s*[A-Z0-9 /_-]{3,80}\s*=+\s*$")
STRONG_NEGATION_CUE_RE = re.compile(
    r"\b(?:denies|denied|deny|without|negative for|free of|absence of)\b",
    re.IGNORECASE,
)
SHORT_NEGATION_CUE_RE = re.compile(r"\b(?:no|not)\b", re.IGNORECASE)
NEGATION_RESET_RE = re.compile(r"\b(?:but|however|although|except)\b|[;:]", re.IGNORECASE)
NEGATION_TERMINATOR_RE = re.compile(
    r"\b(?:but|however|although|except|though|nevertheless|nonetheless|"
    r"has|have|had|with|present(?:s|ed|ing)?|reports?|noted|found)\b|[;:]",
    re.IGNORECASE,
)
STOP_GENERIC_MENTION_TEXTS = {"disease", "disorder", "finding", "condition", "problem"}
CONTEXTUAL_GENERIC_MENTION_TEXTS = {"pain"}
csv.field_size_limit(sys.maxsize)


@dataclass(frozen=True)
class MedcatMention:
    start: int
    end: int
    text: str
    concept_id: int
    concept_name: str
    confidence: float | None = None
    negated: bool = False
    temporal: str | None = None
    experiencer: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--note-file", default=str(NOTE_DEFAULT))
    parser.add_argument("--vocab-dir", default=str(VOCAB_DEFAULT))
    parser.add_argument("--out-root", default=str(OUT_DEFAULT))
    parser.add_argument(
        "--medcat-model-pack",
        help="Path to a MedCAT model pack. If omitted, --cdb-path must be provided.",
    )
    parser.add_argument(
        "--cdb-path",
        help="Path to a MedCAT CDB built from OMOP vocabulary aliases.",
    )
    parser.add_argument(
        "--build-cdb-path",
        help="Build an OMOP SNOMED Condition MedCAT CDB at this path before annotating.",
    )
    parser.add_argument("--max-notes", type=int, default=0, help="0 means all notes.")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--min-sentence-words", type=int, default=6)
    parser.add_argument("--max-sentences-per-note", type=int, default=20)
    parser.add_argument(
        "--include-negated",
        action="store_true",
        help="Keep negated mentions. Default drops them from training rows.",
    )
    return parser.parse_args()


def resolve_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return Path.cwd() / path


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", newline="")
    return path.open("r", newline="")


def _clean_text(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]+", text))


def extract_omop_snomed_condition_aliases(vocab_dir: Path) -> list[dict]:
    """Extract unique aliases for valid standard SNOMED Condition concepts."""
    concept_path = vocab_dir / "CONCEPT.csv"
    synonym_path = vocab_dir / "CONCEPT_SYNONYM.csv"
    if not concept_path.exists():
        raise FileNotFoundError(f"Missing OMOP CONCEPT.csv: {concept_path}")
    if not synonym_path.exists():
        raise FileNotFoundError(f"Missing OMOP CONCEPT_SYNONYM.csv: {synonym_path}")

    concepts: dict[int, str] = {}
    with concept_path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t" if _looks_tsv(concept_path) else ",")
        for row in reader:
            if row.get("domain_id") != "Condition":
                continue
            if row.get("vocabulary_id") != "SNOMED":
                continue
            if row.get("standard_concept") != "S":
                continue
            if row.get("invalid_reason"):
                continue
            concept_id = int(row["concept_id"])
            concepts[concept_id] = row["concept_name"].strip()

    aliases: set[tuple[int, str, str]] = set()
    for concept_id, concept_name in concepts.items():
        aliases.add((concept_id, concept_name, concept_name))

    with synonym_path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t" if _looks_tsv(synonym_path) else ",")
        for row in reader:
            concept_id_raw = row.get("concept_id")
            if not concept_id_raw:
                continue
            concept_id = int(concept_id_raw)
            concept_name = concepts.get(concept_id)
            if concept_name is None:
                continue
            language_concept_id = row.get("language_concept_id")
            if language_concept_id and language_concept_id != ENGLISH_LANGUAGE_CONCEPT_ID:
                continue
            alias = row.get("concept_synonym_name", "").strip()
            if alias:
                aliases.add((concept_id, concept_name, alias))

    return [
        {"concept_id": concept_id, "concept_name": concept_name, "alias": alias}
        for concept_id, concept_name, alias in sorted(aliases, key=lambda item: (item[0], item[2].lower()))
    ]


def load_omop_snomed_condition_names(vocab_dir: Path) -> dict[int, str]:
    """Load canonical OMOP concept names for valid standard SNOMED Conditions."""
    concept_path = vocab_dir / "CONCEPT.csv"
    if not concept_path.exists():
        raise FileNotFoundError(f"Missing OMOP CONCEPT.csv: {concept_path}")

    names: dict[int, str] = {}
    with concept_path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t" if _looks_tsv(concept_path) else ",")
        for row in reader:
            if row.get("domain_id") != "Condition":
                continue
            if row.get("vocabulary_id") != "SNOMED":
                continue
            if row.get("standard_concept") != "S":
                continue
            if row.get("invalid_reason"):
                continue
            names[int(row["concept_id"])] = row["concept_name"].strip()
    return names


def _looks_tsv(path: Path) -> bool:
    with path.open("r", newline="") as handle:
        first = handle.readline()
    return "\t" in first and "," not in first


def sentence_spans(
    text: str,
    min_words: int = 6,
    max_sentences: int = 20,
) -> list[tuple[int, int, str]]:
    """Return sentence spans in original note offsets after light clinical cleanup."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    spans: list[tuple[int, int, str]] = []
    paragraph_chars: list[str] = []
    paragraph_offsets: list[int] = []

    def flush() -> None:
        nonlocal paragraph_chars, paragraph_offsets
        if not paragraph_chars:
            paragraph_chars = []
            paragraph_offsets = []
            return
        paragraph = "".join(paragraph_chars)
        _append_sentence_spans(paragraph, paragraph_offsets, spans, min_words, max_sentences)
        paragraph_chars = []
        paragraph_offsets = []

    cursor = 0
    for raw_line in normalized.splitlines(keepends=True):
        line_start = cursor
        cursor += len(raw_line)
        stripped = raw_line.strip()
        if not stripped:
            flush()
            continue
        if ADMIN_LINE_RE.match(stripped):
            continue
        if DECORATIVE_HEADER_RE.match(stripped):
            flush()
            continue
        if SECTION_HEADER_RE.match(stripped):
            flush()
            continue
        content_start = raw_line.index(stripped)
        line_base = line_start + content_start
        for segment, segment_offsets in _clinical_line_segments(stripped, line_base):
            if not segment.strip():
                continue
            if paragraph_chars:
                paragraph_chars.append(" ")
                paragraph_offsets.append(segment_offsets[0])
            for char, offset in zip(segment, segment_offsets):
                paragraph_chars.append(char)
                paragraph_offsets.append(offset)
            if len(segment) != len(stripped):
                flush()

    flush()
    if max_sentences > 0:
        return spans[:max_sentences]
    return spans


def _clinical_line_segments(line: str, base_offset: int) -> list[tuple[str, list[int]]]:
    matches = list(INLINE_CLINICAL_LABEL_RE.finditer(line))
    if len(matches) >= 2:
        segments: list[tuple[str, list[int]]] = []
        for index, match in enumerate(matches):
            content_start = match.end()
            content_end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
            content = line[content_start:content_end].strip()
            if not content:
                continue
            leading_ws = len(line[content_start:content_end]) - len(line[content_start:content_end].lstrip())
            original_start = content_start + leading_ws
            offsets = [base_offset + idx for idx in range(original_start, original_start + len(content))]
            segments.append((content, offsets))
        return segments

    line_label = CLINICAL_LINE_LABEL_RE.match(line)
    if line_label:
        content = line[line_label.end() :].strip()
        if not content:
            return []
        leading_ws = len(line[line_label.end() :]) - len(line[line_label.end() :].lstrip())
        original_start = line_label.end() + leading_ws
        return [
            (
                content,
                [base_offset + idx for idx in range(original_start, original_start + len(content))],
            )
        ]

    return [(line, [base_offset + idx for idx in range(len(line))])]


def _append_sentence_spans(
    paragraph: str,
    paragraph_offsets: list[int],
    spans: list[tuple[int, int, str]],
    min_words: int,
    max_sentences: int,
) -> None:
    relative_start = 0
    for part in SENTENCE_BOUNDARY_RE.split(paragraph):
        sentence = re.sub(r"\s+", " ", part.strip())
        if not sentence:
            relative_start += len(part) + 1
            continue
        start = paragraph.find(part, relative_start)
        if start < 0:
            start = relative_start
        end = start + len(part)
        relative_start = end
        if _word_count(sentence) < min_words:
            continue
        original_start = paragraph_offsets[start]
        original_end = paragraph_offsets[end - 1] + 1
        spans.append((original_start, original_end, sentence))
        if max_sentences > 0 and len(spans) >= max_sentences:
            return


def iter_discharge_notes(note_file: Path, max_notes: int = 0) -> Iterable[dict]:
    with _open_text(note_file) as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader):
            if max_notes > 0 and idx >= max_notes:
                break
            text = row.get("text")
            if not text:
                continue
            yield {
                "note_id": row.get("note_id"),
                "subject_id": _maybe_int(row.get("subject_id")),
                "hadm_id": _maybe_int(row.get("hadm_id")),
                "text": text,
            }


def _maybe_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def build_medcat_silver_dataset(
    note_file: Path,
    out_root: Path,
    annotator: Callable[[str], list[MedcatMention]],
    medcat_version: str,
    min_sentence_words: int = 6,
    max_sentences_per_note: int = 20,
    max_notes: int = 0,
    include_negated: bool = False,
    canonical_concept_names: dict[int, str] | None = None,
) -> dict:
    if not note_file.exists():
        raise FileNotFoundError(f"Discharge note file not found: {note_file}")

    out_root.mkdir(parents=True, exist_ok=True)
    reports_dir = out_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = out_root / "text_concept_dataset.jsonl"
    summary_path = reports_dir / "summary.json"

    seen_notes = 0
    notes_with_mentions = 0
    written_rows = 0
    skipped_no_sentence_mentions = 0
    label_histogram: Counter[int] = Counter()
    confidence_histogram: Counter[str] = Counter()
    concept_counts: Counter[int] = Counter()
    hard_negative_concept_counts: Counter[int] = Counter()
    sample_rows: list[dict] = []

    with dataset_path.open("w") as handle:
        for note in iter_discharge_notes(note_file, max_notes=max_notes):
            seen_notes += 1
            spans = sentence_spans(
                note["text"],
                min_words=min_sentence_words,
                max_sentences=max_sentences_per_note,
            )
            if not spans:
                skipped_no_sentence_mentions += 1
                continue

            mentions = annotator(note["text"])
            if not mentions:
                skipped_no_sentence_mentions += 1
                continue
            notes_with_mentions += 1

            for sentence_index, (sent_start, sent_end, sentence) in enumerate(spans):
                negation_scopes = _negation_scopes(sentence)
                sentence_mentions: list[tuple[MedcatMention, bool]] = [
                    (
                        mention,
                        mention.negated
                        or _is_rule_negated(
                            sentence,
                            mention.start - sent_start,
                            negation_scopes=negation_scopes,
                        ),
                    )
                    for mention in mentions
                    if sent_start <= mention.start
                    and mention.end <= sent_end
                ]
                sentence_mentions = _prune_generic_mentions(sentence_mentions)
                if not sentence_mentions:
                    continue
                positive_mentions = [
                    mention
                    for mention, is_negated in sentence_mentions
                    if include_negated or not is_negated
                ]
                positive_mentions = _refine_positive_mentions(positive_mentions)
                hard_negative_mentions = [
                    mention for mention, is_negated in sentence_mentions if is_negated
                ]
                if not positive_mentions:
                    continue
                row = _build_row(
                    note,
                    sentence_index,
                    sentence,
                    positive_mentions,
                    hard_negative_mentions if not include_negated else [],
                    canonical_concept_names=canonical_concept_names,
                )
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                written_rows += 1
                label_histogram[len(row["concept_ids"])] += 1
                for mention in positive_mentions:
                    concept_counts[mention.concept_id] += 1
                    if mention.confidence is not None:
                        confidence_histogram[_confidence_bucket(mention.confidence)] += 1
                for mention in hard_negative_mentions:
                    hard_negative_concept_counts[mention.concept_id] += 1
                if len(sample_rows) < 20:
                    sample_rows.append(row)

    summary = {
        "label_source": LABEL_SOURCE,
        "note_scope": "discharge",
        "note_file": str(note_file),
        "dataset_path": str(dataset_path),
        "medcat_version": medcat_version,
        "min_sentence_words": min_sentence_words,
        "max_sentences_per_note": max_sentences_per_note,
        "max_notes": max_notes,
        "include_negated": include_negated,
        "source_notes": seen_notes,
        "notes_with_mentions": notes_with_mentions,
        "skipped_no_sentence_mentions": skipped_no_sentence_mentions,
        "written_rows": written_rows,
        "unique_concepts": len(concept_counts),
        "unique_hard_negative_concepts": len(hard_negative_concept_counts),
        "label_count_histogram": dict(sorted(label_histogram.items())),
        "mention_confidence_histogram": dict(sorted(confidence_histogram.items())),
        "top_concepts": [
            {"concept_id": concept_id, "mention_count": count}
            for concept_id, count in concept_counts.most_common(50)
        ],
        "top_hard_negative_concepts": [
            {"concept_id": concept_id, "mention_count": count}
            for concept_id, count in hard_negative_concept_counts.most_common(50)
        ],
        "sample_rows": sample_rows,
        "vocabulary_filter": "domain_id=Condition; vocabulary_id=SNOMED; standard_concept=S; invalid_reason IS NULL",
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    return summary


def _build_row(
    note: dict,
    sentence_index: int,
    sentence: str,
    mentions: list[MedcatMention],
    hard_negative_mentions: list[MedcatMention] | None = None,
    canonical_concept_names: dict[int, str] | None = None,
) -> dict:
    hard_negative_mentions = hard_negative_mentions or []
    canonical_concept_names = canonical_concept_names or {}
    ordered_mentions = sorted(mentions, key=lambda mention: (mention.start, mention.end, mention.concept_id))
    ordered_hard_negative_mentions = sorted(
        hard_negative_mentions,
        key=lambda mention: (mention.start, mention.end, mention.concept_id),
    )
    concept_names_by_id: dict[int, str] = {}
    for mention in ordered_mentions:
        concept_names_by_id.setdefault(
            mention.concept_id,
            canonical_concept_names.get(mention.concept_id, mention.concept_name),
        )
    concept_ids = sorted(concept_names_by_id)
    hard_negative_names_by_id: dict[int, str] = {}
    for mention in ordered_hard_negative_mentions:
        hard_negative_names_by_id.setdefault(
            mention.concept_id,
            canonical_concept_names.get(mention.concept_id, mention.concept_name),
        )
    hard_negative_concept_ids = sorted(hard_negative_names_by_id)
    return {
        "note_id": note["note_id"],
        "subject_id": note["subject_id"],
        "hadm_id": note["hadm_id"],
        "sentence_index": sentence_index,
        "text": sentence,
        "concept_ids": concept_ids,
        "concept_names": [concept_names_by_id[concept_id] for concept_id in concept_ids],
        "hard_negative_concept_ids": hard_negative_concept_ids,
        "hard_negative_concept_names": [
            hard_negative_names_by_id[concept_id]
            for concept_id in hard_negative_concept_ids
        ],
        "mentions": [
            {
                "start": mention.start,
                "end": mention.end,
                "text": mention.text,
                "concept_id": mention.concept_id,
                "concept_ids": [mention.concept_id],
                "concept_name": canonical_concept_names.get(mention.concept_id, mention.concept_name),
                "confidence": mention.confidence,
                "negated": mention.negated,
                "assertion": "present",
            }
            for mention in ordered_mentions
        ],
        "hard_negative_mentions": [
            {
                "start": mention.start,
                "end": mention.end,
                "text": mention.text,
                "concept_id": mention.concept_id,
                "concept_ids": [mention.concept_id],
                "concept_name": canonical_concept_names.get(mention.concept_id, mention.concept_name),
                "confidence": mention.confidence,
                "negated": True,
                "assertion": "negated",
            }
            for mention in ordered_hard_negative_mentions
        ],
        "label_source": LABEL_SOURCE,
    }


def _refine_positive_mentions(mentions: list[MedcatMention]) -> list[MedcatMention]:
    filtered = [
        mention
        for mention in mentions
        if mention.concept_id not in ALWAYS_DROP_GENERIC_CONCEPT_IDS
    ]
    if len(filtered) < 2:
        return filtered

    refined: list[MedcatMention] = []
    for mention in filtered:
        if mention.concept_id in OVERLAP_DROP_GENERIC_CONCEPT_IDS and _is_nested_in_specific_mention(
            mention,
            filtered,
        ):
            continue
        refined.append(mention)
    return refined


def _is_nested_in_specific_mention(
    candidate: MedcatMention,
    mentions: list[MedcatMention],
) -> bool:
    for other in mentions:
        if other is candidate:
            continue
        if other.concept_id == candidate.concept_id:
            continue
        if other.start <= candidate.start and candidate.end <= other.end:
            if (other.end - other.start) > (candidate.end - candidate.start):
                return True
    return False


def _confidence_bucket(confidence: float) -> str:
    lower = int(confidence * 10) / 10
    upper = lower + 0.1
    return f"{lower:.1f}-{upper:.1f}"


def _normalized_mention_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _prune_generic_mentions(
    mentions: list[tuple[MedcatMention, bool]],
) -> list[tuple[MedcatMention, bool]]:
    pruned: list[tuple[MedcatMention, bool]] = []
    for mention, is_negated in mentions:
        normalized = _normalized_mention_text(mention.text)
        if normalized in STOP_GENERIC_MENTION_TEXTS:
            continue
        if normalized in CONTEXTUAL_GENERIC_MENTION_TEXTS and _has_more_specific_covering_mention(
            mention,
            mentions,
        ):
            continue
        pruned.append((mention, is_negated))
    return pruned


def _has_more_specific_covering_mention(
    target: MedcatMention,
    mentions: list[tuple[MedcatMention, bool]],
) -> bool:
    for mention, _ in mentions:
        if mention is target:
            continue
        if mention.start <= target.start and target.end <= mention.end:
            if (mention.end - mention.start) > (target.end - target.start):
                return True
    return False


def _is_rule_negated(
    sentence: str,
    relative_mention_start: int,
    negation_scopes: list[tuple[int, int]] | None = None,
) -> bool:
    if negation_scopes is None:
        negation_scopes = _negation_scopes(sentence)
    if any(start <= relative_mention_start < end for start, end in negation_scopes):
        return True

    window = sentence[max(0, relative_mention_start - 80) : relative_mention_start]
    reset_matches = list(NEGATION_RESET_RE.finditer(window))
    if reset_matches:
        window = window[reset_matches[-1].end() :]
    if STRONG_NEGATION_CUE_RE.search(window):
        return True
    short_window = window[-25:]
    return SHORT_NEGATION_CUE_RE.search(short_window) is not None


def _negation_scopes(sentence: str) -> list[tuple[int, int]]:
    scopes: list[tuple[int, int]] = []
    for cue in _iter_negation_cues(sentence):
        scope_start = cue.end()
        scope_end = _scope_end(sentence, scope_start)
        if scope_start < scope_end:
            scopes.append((scope_start, scope_end))
    return scopes


def _iter_negation_cues(sentence: str):
    matches = list(STRONG_NEGATION_CUE_RE.finditer(sentence))
    matches.extend(SHORT_NEGATION_CUE_RE.finditer(sentence))
    return sorted(matches, key=lambda match: match.start())


def _scope_end(sentence: str, scope_start: int) -> int:
    terminator = NEGATION_TERMINATOR_RE.search(sentence, scope_start)
    if terminator:
        return terminator.start()
    sentence_end = re.search(r"[.!?]", sentence[scope_start:])
    if sentence_end:
        return scope_start + sentence_end.start()
    return len(sentence)


def build_medcat_cdb(vocab_dir: Path, cdb_path: Path) -> None:
    """Build a MedCAT CDB from OMOP aliases.

    MedCAT's public API has changed across releases, so this function keeps the
    import local and fails with an actionable error when the installed package is
    incompatible.
    """
    aliases = extract_omop_snomed_condition_aliases(vocab_dir)
    try:
        from medcat.model_creation.cdb_maker import CDBMaker
        from medcat.config import Config
    except ImportError as exc:
        raise SystemExit(
            "MedCAT is required to build a CDB. Install it with: python3 -m pip install --user medcat"
        ) from exc

    rows = [
        {
            "cui": str(alias["concept_id"]),
            "name": alias["alias"],
            "ontologies": "SNOMED",
            "name_status": "P",
            "type_ids": "T047",
            "description": alias["concept_name"],
        }
        for alias in aliases
    ]
    cdb_path.mkdir(parents=True, exist_ok=True)
    tmp_csv = cdb_path.parent / f"{cdb_path.name}.concepts.csv"
    tmp_csv.parent.mkdir(parents=True, exist_ok=True)
    with tmp_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["cui", "name", "ontologies", "name_status", "type_ids", "description"],
        )
        writer.writeheader()
        writer.writerows(rows)

    config = Config()
    config.components.linking.comp_name = "primary_name_only_linker"
    maker = CDBMaker(config)
    cdb = maker.prepare_csvs([str(tmp_csv)], full_build=True)
    cdb.save(str(cdb_path))


def make_medcat_annotator(
    medcat_model_pack: Path | None,
    cdb_path: Path | None,
) -> tuple[Callable[[str], list[MedcatMention]], str]:
    try:
        import medcat
        from medcat.cat import CAT
    except ImportError as exc:
        raise SystemExit(
            "MedCAT is required for annotation. Install it with: python3 -m pip install --user medcat"
        ) from exc

    if medcat_model_pack is not None:
        cat = CAT.load_model_pack(str(medcat_model_pack))
    elif cdb_path is not None:
        try:
            from medcat.cdb import CDB
            from medcat.config import Config
        except ImportError as exc:
            raise SystemExit("Installed MedCAT does not expose CDB/Config APIs needed for --cdb-path") from exc
        cdb = CDB.load(str(cdb_path))
        cdb.config.components.linking.comp_name = "primary_name_only_linker"
        cat = CAT(cdb=cdb, config=cdb.config)
    else:
        raise ValueError("Provide --medcat-model-pack or --cdb-path")

    def annotate(text: str) -> list[MedcatMention]:
        result = cat.get_entities(text)
        entities = result.get("entities", result)
        if isinstance(entities, dict):
            values = entities.values()
        else:
            values = entities
        mentions: list[MedcatMention] = []
        for entity in values:
            concept_id_raw = entity.get("cui") or entity.get("id")
            if concept_id_raw is None:
                continue
            context = entity.get("context_similarity")
            acc = entity.get("acc")
            confidence = float(context if context is not None else acc) if (context is not None or acc is not None) else None
            mentions.append(
                MedcatMention(
                    start=int(entity["start"]),
                    end=int(entity["end"]),
                    text=entity.get("source_value") or text[int(entity["start"]) : int(entity["end"])],
                    concept_id=int(concept_id_raw),
                    concept_name=entity.get("pretty_name") or entity.get("detected_name") or str(concept_id_raw),
                    confidence=confidence,
                    negated=_is_negated(entity),
                    temporal=_entity_context_value(entity, "Time"),
                    experiencer=_entity_context_value(entity, "Experiencer"),
                )
            )
        return mentions

    version = getattr(medcat, "__version__", "unknown")
    return annotate, version


def _is_negated(entity: dict) -> bool:
    negated = entity.get("negated")
    if isinstance(negated, bool):
        return negated
    status = _entity_context_value(entity, "Negation") or _entity_context_value(entity, "Presence")
    if status is None:
        return False
    return str(status).lower() in {"negated", "false", "absent", "0"}


def _entity_context_value(entity: dict, name: str) -> str | None:
    meta = entity.get("meta_anns") or entity.get("meta_annotations") or {}
    value = meta.get(name)
    if isinstance(value, dict):
        return value.get("value")
    if value is None:
        return None
    return str(value)


def main() -> None:
    args = parse_args()
    note_file = resolve_path(args.note_file)
    out_root = resolve_path(args.out_root)
    vocab_dir = resolve_path(args.vocab_dir)
    cdb_path = resolve_path(args.cdb_path) if args.cdb_path else None

    if args.build_cdb_path:
        cdb_path = resolve_path(args.build_cdb_path)
        build_medcat_cdb(vocab_dir, cdb_path)

    annotator, medcat_version = make_medcat_annotator(
        medcat_model_pack=resolve_path(args.medcat_model_pack) if args.medcat_model_pack else None,
        cdb_path=cdb_path,
    )
    summary = build_medcat_silver_dataset(
        note_file=note_file,
        out_root=out_root,
        annotator=annotator,
        medcat_version=medcat_version,
        min_sentence_words=args.min_sentence_words,
        max_sentences_per_note=args.max_sentences_per_note,
        max_notes=args.max_notes,
        include_negated=args.include_negated,
        canonical_concept_names=load_omop_snomed_condition_names(vocab_dir),
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
