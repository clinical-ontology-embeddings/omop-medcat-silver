# Synthetic Example Rows

`synthetic_text_concept_dataset.jsonl` is a tiny fabricated example of the
private row schema produced by `scripts/build_medcat_silver_dataset.py`.

The rows are not derived from MIMIC-IV-Note, are not patient records, and do
not contain real note, subject, admission, or mention-offset identifiers. They
exist only so users can inspect the JSONL shape before rebuilding the private
dataset locally from authorized inputs.

The full generated dataset remains uncommitted and must be rebuilt locally by
credentialed users.
