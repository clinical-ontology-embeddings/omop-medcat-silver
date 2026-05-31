# MedCAT Silver Public Release Boundary

This is the GitHub-facing release note for the OMOP MedCAT Silver sentence
dataset recipe. The public artifact is a regeneration recipe, not the
generated JSONL dataset.

## Public Artifact

Committed to GitHub:

```text
scripts/build_medcat_silver_dataset.py
scripts/make_medcat_silver_public_manifest.py
requirements.txt
examples/README.md
examples/synthetic_text_concept_dataset.jsonl
docs/dataset/medcat_silver_generation.md
docs/dataset/medcat_silver_full_v1_public_manifest.json
tests/medcat_silver_dataset_test.py
tests/test_make_medcat_silver_public_manifest.py
```

Not committed to GitHub:

```text
data/01_raw/mimic-iv-note/
data/01_raw/vocabulary_v5/
data/03_processed/text_concept_dataset/medcat_silver_full_v1/text_concept_dataset.jsonl
data/03_processed/text_concept_dataset/medcat_silver_full_v1/reports/summary.json
data/03_processed/text_concept_dataset/medcat_silver_v1/medcat_omop_snomed_condition_cdb
```

The generated JSONL contains MIMIC-derived sentence text, note identifiers,
subject identifiers, admission identifiers, and mention offsets. It should be
rebuilt locally by credentialed users from their own authorized copies of the
source data.

The only committed JSONL rows are the fabricated schema examples under
`examples/synthetic_text_concept_dataset.jsonl`. They are not generated from
MIMIC-IV-Note and are not part of the private dataset.

## Purpose

OMOP MedCAT Silver exists to publish a reproducible recipe for a restricted
clinical silver-label dataset without publishing the restricted dataset rows.
The public release contains the generator, aggregate manifest, documentation,
tests, and leak-audit script. Credentialed users provide the required clinical
notes, OMOP vocabulary files, and locally rebuilt MedCAT CDB in their own
environment.

The private output is intended for sentence-level weak supervision of
OMOP/SNOMED Condition concept linking. Each retained sentence or short clinical
statement is mapped to OMOP Condition `concept_id` labels from a local MedCAT
annotation pass, while negated mentions are retained separately as hard-negative
metadata for diagnostics or training.

Example uses:

- Rebuild the private JSONL dataset locally from authorized source files.
- Train or compare OMOP Condition concept-linking models using the same
  regeneration contract.
- Publish aggregate counts and manifest metadata without exposing patient text,
  note identifiers, subject identifiers, admission identifiers, or mention
  offsets.
- Audit release branches before publication to block generated rows, local
  summaries, MedCAT CDB/model-pack files, and private row-level examples.

## Synthetic Example Rows

`examples/synthetic_text_concept_dataset.jsonl` contains two fabricated rows
that demonstrate the generator output shape:

- a present positive mention with a negated hard-negative mention
- a present positive mention without hard-negative metadata

The examples use `example-*` identifiers and synthetic sentence text. They are
included only to make the public recipe easier to inspect before local
regeneration.

## Required Local Inputs

| Input | Local path | Public status |
|---|---|---|
| MIMIC-IV-Note discharge notes | `data/01_raw/mimic-iv-note/2.2/note/discharge.csv.gz` | credentialed PhysioNet input; not redistributed |
| OMOP vocabulary v5 | `data/01_raw/vocabulary_v5` | local vocabulary download; not redistributed |
| OMOP/SNOMED Condition MedCAT CDB | `data/03_processed/text_concept_dataset/medcat_silver_v1/medcat_omop_snomed_condition_cdb` | rebuilt locally from OMOP vocabulary |

## Software Requirements

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

`medcat` is required for local CDB construction and annotation. Public tests use
synthetic fixtures and do not require restricted clinical or vocabulary inputs.

## Regeneration

Build or reuse the OMOP/SNOMED Condition CDB, then run:

```bash
python3 scripts/build_medcat_silver_dataset.py \
  --note-file data/01_raw/mimic-iv-note/2.2/note/discharge.csv.gz \
  --out-root data/03_processed/text_concept_dataset/medcat_silver_full_v1 \
  --cdb-path data/03_processed/text_concept_dataset/medcat_silver_v1/medcat_omop_snomed_condition_cdb \
  --max-notes 0 \
  --min-sentence-words 6 \
  --max-sentences-per-note 20
```

Expected aggregate output from the current full run:

| Metric | Value |
|---|---:|
| Source notes | `331,793` |
| Notes with mentions | `331,792` |
| Written rows | `2,266,848` |
| Unique positive concepts | `11,629` |
| Unique hard-negative concepts | `3,725` |
| MedCAT version | `2.7.0` |

The public aggregate manifest is:

```text
docs/dataset/medcat_silver_full_v1_public_manifest.json
```

Regenerate it from a private local summary with:

```bash
python3 scripts/make_medcat_silver_public_manifest.py \
  --summary-json data/03_processed/text_concept_dataset/medcat_silver_full_v1/reports/summary.json \
  --out docs/dataset/medcat_silver_full_v1_public_manifest.json
```

## Publication Safety Checks

Before pushing a public release branch:

```bash
python3 scripts/audit_public_dataset_release.py
python3 -m pytest tests/medcat_silver_dataset_test.py tests/test_make_medcat_silver_public_manifest.py tests/test_audit_public_dataset_release.py -q
python3 -m json.tool docs/dataset/medcat_silver_full_v1_public_manifest.json >/dev/null
```

## Source Policy

PhysioNet's current MIMIC guidance says derived datasets or models should be
treated as sensitive and, if shared, should be shared under the same agreement
as the source data. This GitHub release therefore exposes only the recipe and
aggregate metadata; it does not redistribute MIMIC-derived rows.

## License

Code, documentation, tests, and public aggregate manifests in this repository
are distributed under the MIT License. Generated dataset rows are not
distributed by this repository. MIMIC-IV-Note, OMOP vocabulary files, and any
locally rebuilt MedCAT CDB or model-pack artifacts remain governed by their
respective upstream access terms and licenses.

## Acknowledgements

This research was supported by the AI Computing Infrastructure Enhancement
(GPU Rental Support) User Support Program funded by the Ministry of Science
and ICT (MSIT), Republic of Korea (No. RQT-25-120164).
