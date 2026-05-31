# OMOP MedCAT Silver

**A recipe-only public release for rebuilding an OMOP/SNOMED MedCAT silver
dataset from credentialed clinical notes.** This repository publishes the
generation code, documentation, aggregate manifest, synthetic schema examples,
and release-boundary checks. It does not publish the generated dataset rows.

The generated private JSONL contains MIMIC-IV-Note-derived sentence text, note
identifiers, subject identifiers, admission identifiers, and mention offsets.
Credentialed users should rebuild it locally from their own authorized source
data.

## At a Glance

| Field | Value |
|---|---|
| Release type | Dataset regeneration recipe with aggregate public manifest |
| Generated private output | Sentence-level OMOP/SNOMED Condition silver labels from a local MedCAT pass |
| Public artifacts | Generator scripts, documentation, synthetic example rows, aggregate manifest, tests, and release-boundary audit |
| Restricted inputs | MIMIC-IV-Note discharge notes, OMOP vocabulary files, and a locally rebuilt MedCAT CDB |
| Distribution boundary | Generated clinical rows, local summaries, CDB/model-pack artifacts, and source data are not distributed |
| License | MIT for repository code, documentation, tests, and public aggregate metadata |

## Purpose

OMOP MedCAT Silver makes a restricted clinical silver-label dataset
reproducible without redistributing the restricted rows themselves. The public
release separates the auditable parts of the work from private artifacts:
credentialed users provide the clinical notes and vocabulary files locally,
while this repository provides the recipe, manifest generator, schema example,
documentation, and leak guards.

The generated private dataset is intended for sentence-level weak supervision
of OMOP/SNOMED Condition concept linking. Each retained sentence or short
clinical statement is mapped to OMOP Condition `concept_id` labels detected by
a locally built MedCAT CDB. Negated mentions are retained separately as
hard-negative metadata for diagnostics or training.

Example uses:

- Rebuild a private sentence-to-concept training set from an authorized local
  MIMIC-IV-Note copy and an OMOP vocabulary download.
- Compare concept-linking systems against the same aggregate dataset contract
  without sharing patient text or document identifiers.
- Pretrain or fine-tune a clinical concept linker on OMOP Condition labels,
  then publish only aggregate counts, metrics, and release-safe manifests.
- Audit a public release branch to ensure generated JSONL rows, local
  summaries, MedCAT CDB files, identifiers, mention offsets, and clinical text
  were not committed.

## Repository Layout

| Path | Purpose |
|---|---|
| `scripts/build_medcat_silver_dataset.py` | Builds the private sentence-level silver dataset from local authorized inputs |
| `scripts/make_medcat_silver_public_manifest.py` | Converts a private local summary into a GitHub-safe aggregate manifest |
| `scripts/audit_public_dataset_release.py` | Blocks private rows, local summaries, MedCAT CDB/model-pack artifacts, and leak markers |
| `docs/dataset/medcat_silver_generation.md` | Local generation notes and artifact contract |
| `docs/dataset/medcat_silver_public_release.md` | Public release-boundary documentation |
| `docs/dataset/medcat_silver_full_v1_public_manifest.json` | Aggregate public manifest only; no row examples or private paths |
| `examples/synthetic_text_concept_dataset.jsonl` | Tiny fabricated JSONL schema example, not MIMIC-derived |
| `tests/` | Dataset builder, manifest, schema-example, and audit regression tests |
| `requirements.txt` | Pinned public recipe, MedCAT generation, and downstream adapter dependencies |

## Requirements

The public recipe is tested with Python 3.11. `requirements.txt` includes the
public audit/test dependencies, local MedCAT generation stack, and downstream
adapter runtime for users who train concept linkers on regenerated private rows.

```text
medcat==2.7.0
pytest==9.0.3
spacy==3.8.14
numpy==2.1.2
pandas==2.3.3
scipy==1.15.3
scikit-learn==1.7.2
torch==2.10.0
transformers==5.5.4
sentence-transformers==5.1.2
```

`medcat` is required when building the OMOP/SNOMED Condition CDB or annotating
notes. Public tests use synthetic fixtures and do not require restricted
clinical or vocabulary inputs.

## Quick Start

Install the public recipe and test dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

Run the public checks:

```bash
python3 -m pytest tests/medcat_silver_dataset_test.py tests/test_make_medcat_silver_public_manifest.py tests/test_audit_public_dataset_release.py -q
python3 scripts/audit_public_dataset_release.py
python3 -m json.tool docs/dataset/medcat_silver_full_v1_public_manifest.json >/dev/null
```

The focused public tests use synthetic fixtures and do not require access to
MIMIC-IV-Note, OMOP vocabulary files, or generated dataset rows.

## Synthetic Example Rows

This repository includes a tiny fabricated JSONL file for schema inspection:

```text
examples/synthetic_text_concept_dataset.jsonl
```

These example rows are not derived from MIMIC-IV-Note and do not contain real
patient text, note identifiers, subject identifiers, admission identifiers, or
clinical mention offsets. They only show the row shape emitted by the
generator, including positive OMOP/SNOMED Condition labels and negated
hard-negative mentions.

Single synthetic sample:

```json
{
  "note_id": "example-note-001",
  "subject_id": "example-subject-001",
  "hadm_id": "example-encounter-001",
  "sentence_index": 0,
  "text": "Synthetic example sentence reports pneumonia and no edema today.",
  "concept_ids": [111],
  "concept_names": ["Pneumonia"],
  "hard_negative_concept_ids": [433595],
  "hard_negative_concept_names": ["Edema"],
  "mentions": [
    {
      "start": 35,
      "end": 44,
      "text": "pneumonia",
      "concept_id": 111,
      "concept_ids": [111],
      "concept_name": "Pneumonia",
      "confidence": 1.0,
      "negated": false,
      "assertion": "present"
    }
  ],
  "hard_negative_mentions": [
    {
      "start": 52,
      "end": 57,
      "text": "edema",
      "concept_id": 433595,
      "concept_ids": [433595],
      "concept_name": "Edema",
      "confidence": 1.0,
      "negated": true,
      "assertion": "negated"
    }
  ],
  "label_source": "medcat_omop_snomed_condition"
}
```

This row demonstrates one present concept label and one negated hard-negative
mention.

## Required Local Inputs

| Input | Expected local path | Public status |
|---|---|---|
| MIMIC-IV-Note discharge notes | `data/01_raw/mimic-iv-note/2.2/note/discharge.csv.gz` | PhysioNet credentialed input; not redistributed |
| OMOP vocabulary v5 | `data/01_raw/vocabulary_v5` | Local vocabulary download; not redistributed |
| OMOP/SNOMED Condition MedCAT CDB | `data/03_processed/text_concept_dataset/medcat_silver_v1/medcat_omop_snomed_condition_cdb` | Rebuilt locally from OMOP vocabulary |

PhysioNet's current MIMIC guidance says derived datasets or models should be
treated as sensitive and, if shared, should be shared under the same agreement
as the source data. This public repository therefore provides only code,
documentation, synthetic examples, and aggregate metadata.

## Local Regeneration

Build or reuse the OMOP/SNOMED Condition MedCAT CDB, then run:

```bash
python3 scripts/build_medcat_silver_dataset.py \
  --note-file data/01_raw/mimic-iv-note/2.2/note/discharge.csv.gz \
  --out-root data/03_processed/text_concept_dataset/medcat_silver_full_v1 \
  --cdb-path data/03_processed/text_concept_dataset/medcat_silver_v1/medcat_omop_snomed_condition_cdb \
  --max-notes 0 \
  --min-sentence-words 6 \
  --max-sentences-per-note 20
```

The private local run writes the generated JSONL rows and a private summary
under the local `data/` tree. Those artifacts are intentionally ignored and
blocked by the public audit.

## Public Manifest

After a private local regeneration, create a GitHub-safe manifest from the
private summary:

```bash
python3 scripts/make_medcat_silver_public_manifest.py \
  --summary-json data/03_processed/text_concept_dataset/medcat_silver_full_v1/reports/summary.json \
  --out docs/dataset/medcat_silver_full_v1_public_manifest.json
```

The manifest generator strips row-level example content and local absolute
paths. It keeps only aggregate statistics and reproducibility metadata.

Expected aggregate output from the current full regeneration run:

| Metric | Value |
|---|---:|
| Source notes | `331,793` |
| Notes with mentions | `331,792` |
| Written rows | `2,266,848` |
| Unique positive concepts | `11,629` |
| Unique hard-negative concepts | `3,725` |
| MedCAT version | `2.7.0` |

## Release Boundary

Public artifacts:

- Regeneration scripts and manifest generator.
- Aggregate public manifest.
- Documentation and synthetic schema examples.
- Tests and release-boundary audit.

Private artifacts not committed:

- `data/01_raw/mimic-iv-note/`
- `data/01_raw/vocabulary_v5/`
- `data/03_processed/text_concept_dataset/medcat_silver_full_v1/text_concept_dataset.jsonl`
- `data/03_processed/text_concept_dataset/medcat_silver_full_v1/reports/summary.json`
- `data/03_processed/text_concept_dataset/medcat_silver_v1/medcat_omop_snomed_condition_cdb`
- Any MIMIC-derived text, document identifiers, patient identifiers, admission
  identifiers, mention offsets, MedCAT CDB files, or model-pack artifacts.

## License and External Terms

Repository code, documentation, tests, synthetic examples, and public aggregate
metadata are distributed under the [MIT License](LICENSE). The MIT license text
is also available from the Open Source Initiative:
https://opensource.org/license/mit.

Generated dataset rows are not distributed by this repository. External
resources remain governed by their own terms:

- MIMIC-IV-Note: https://physionet.org/content/mimic-iv-note/
- PhysioNet credentialed access and data-use terms: https://physionet.org/content/mimiciv/view-dua/1.0/
- OMOP Common Data Model: https://www.ohdsi.org/data-standardization/the-common-data-model/
- OHDSI Athena vocabulary access: https://athena.ohdsi.org/
- MedCAT: https://github.com/CogStack/MedCAT

## Citation

If you use this recipe, cite the corresponding publication when available and
follow the data usage terms for all upstream clinical and ontology resources.

## Acknowledgements

This research was supported by the AI Computing Infrastructure Enhancement
(GPU Rental Support) User Support Program funded by the Ministry of Science
and ICT (MSIT), Republic of Korea (No. RQT-25-120164).
