# MedCAT Silver Sentence Dataset Generation

## 목적

MIMIC-IV discharge note에는 문장별 OMOP concept label이 없다. OMOP
`condition_occurrence`는 admission/visit 단위 condition label이므로, 한
문장에 실제로 언급되지 않은 concept까지 붙을 수 있다.

이 문서는 discharge note 문장 안에 실제로 등장한 disease/symptom mention을
MedCAT으로 찾아 OMOP SNOMED Condition `concept_id`에 연결하는
`MedCAT-derived mention-level silver label dataset` 생성 방식을 정리한다.

```text
MIMIC-IV discharge note
  -> sentence / short clinical statement spans
  -> MedCAT mention detection
  -> OMOP SNOMED Condition concept_id
  -> present mentions = positives
  -> negated mentions = hard negatives
```

## Public GitHub Boundary

GitHub 공개 대상은 이 문서와 재생성 스크립트, aggregate manifest다. 생성된
`text_concept_dataset.jsonl` 본체와 private `summary.json`은 MIMIC-derived
sentence text, note identifier, subject/admission identifier, mention offset을
포함하므로 GitHub에 올리지 않는다.

공개용 경계 문서와 manifest:

```text
docs/dataset/medcat_silver_public_release.md
docs/dataset/medcat_silver_full_v1_public_manifest.json
scripts/make_medcat_silver_public_manifest.py
```

## 입력 데이터

| Input | Path |
|---|---|
| MIMIC-IV discharge notes | `data/01_raw/mimic-iv-note/2.2/note/discharge.csv.gz` |
| OMOP vocabulary v5 | `data/01_raw/vocabulary_v5` |
| MedCAT CDB | `data/03_processed/text_concept_dataset/medcat_silver_v1/medcat_omop_snomed_condition_cdb` |

MedCAT CDB는 로컬 OMOP vocabulary에서 만든다.

```text
CONCEPT.csv
CONCEPT_SYNONYM.csv
  -> SNOMED standard Condition concepts
  -> concept_name + English synonyms
  -> MedCAT CDB
```

## MedCAT CDB Target

MedCAT 자체가 OMOP vocabulary 전용으로 만들어진 도구는 아니다. MedCAT은
clinical mention detection/linking engine이고, 실제 target concept universe는
어떤 CDB 또는 model pack을 쓰는지에 따라 결정된다. 일반적인 MedCAT 사용에서는
UMLS 기반 CDB/model pack을 많이 쓴다. UMLS는 SNOMED CT, ICD, MeSH, RxNorm 등
여러 biomedical vocabulary를 CUI 중심으로 묶기 때문에 범용 clinical concept
linking target으로 쓰기 좋다.

이 recipe에서는 연구 target이 OMOP Condition/SNOMED hierarchy이므로 CDB를 처음부터
OMOP vocabulary에서 만들었다. 즉 MedCAT CDB의 `cui` field에 UMLS CUI가 아니라
OMOP `concept_id`를 넣고, alias/name은 OMOP `CONCEPT.csv`와
`CONCEPT_SYNONYM.csv`에서 가져온다.

```text
General UMLS-backed MedCAT
clinical mention -> MedCAT -> UMLS CUI

OMOP-backed MedCAT
clinical mention -> MedCAT -> OMOP SNOMED Condition concept_id
```

UMLS CUI를 먼저 얻은 뒤 OMOP으로 매핑하는 방식도 가능하다. 보통은 UMLS
`MRCONSO`에서 `SAB = SNOMEDCT_US` row를 찾고, 그 `CODE`를 OMOP
`CONCEPT.concept_code`와 join해서 OMOP SNOMED `concept_id`를 얻는다.

```text
UMLS CUI
  -> MRCONSO SNOMEDCT_US CODE
  -> OMOP CONCEPT.concept_code
  -> OMOP concept_id
```

다만 이 경로는 하나의 CUI가 여러 SNOMED code에 연결되거나, OMOP에서 non-standard
또는 invalid concept로 연결될 수 있다. 이 recipe는 sentence label, concept table,
ontology edge, hierarchy metric을 모두 같은 OMOP `concept_id` space에 맞추기
위해 처음부터 OMOP SNOMED Condition CDB를 사용하는 쪽을 선택했다.

## Vocabulary Filter

MedCAT dictionary에 넣는 concept은 아래 조건으로 제한한다.

```text
domain_id = Condition
vocabulary_id = SNOMED
standard_concept = S
invalid_reason IS NULL
CONCEPT_SYNONYM.language_concept_id = 4180186
```

`concept_id`는 OMOP `concept_id`를 그대로 사용한다. `concept_name`은 MedCAT이
매칭한 alias가 아니라 OMOP `CONCEPT.csv`의 canonical `concept_name`으로
저장한다. 예를 들어 MedCAT alias가 `Dolor`로 잡혀도 `concept_id=4329041`의
출력 이름은 `Pain`이다.

## Sentence / Statement Segmentation

출력 row의 `text`는 discharge note 전체가 아니라 sentence 또는 짧은 clinical
statement다.

기본적으로 문장부호로 sentence span을 만들지만, discharge note에는 다음과
같은 exam/ROS block이 많다.

```text
VS: ... GEN: ... HEENT: ... CV: ... ABD: ... EXTREM: ...
```

따라서 splitter는 다음도 statement boundary로 처리한다.

- inline uppercase clinical labels: `GEN:`, `HEENT:`, `CV:`, `RESP:`, `GI:`
- line-leading exam labels: `VS:`, `GEN:`, `HEENT:`, `ABD:`, `EXTREM:`, `NEURO:`
- decorative section headers: `===== ADMISSION/DISCHARGE EXAM =====`

목표는 이런 긴 block을 그대로 row로 쓰지 않고, 다음처럼 짧게 나누는 것이다.

```text
GEN: Thin anxious woman, no acute distress
ABD: Soft, non-tender, non-distended
EXTREM: no edema
```

## Mention Linking

MedCAT은 note 전체 텍스트에 대해 실행한다. 이후 mention의 original note
`start/end` offset이 어떤 sentence/statement span에 포함되는지 확인해서 해당
row에 붙인다.

positive 조건:

- mention이 sentence/statement span 안에 있음
- OMOP SNOMED standard Condition concept로 연결됨
- negation scope 안에 있지 않음
- generic concept refinement 후에도 남아 있음

negated mention은 positive에서 제외하지만 버리지 않고 hard negative로 저장한다.

## Negation 처리

negation은 sentence-local scope rule을 사용한다.

negation cue:

```text
denies, denied, deny, without, negative for, free of, absence of, no, not
```

scope terminator:

```text
but, however, although, except, though, nevertheless, nonetheless,
has, have, had, with, presents, reports, noted, found, ;, :
```

예:

```text
She denies edema but has pneumonia.
```

해석:

```text
pneumonia = positive
edema = hard negative
```

또한 coordinated list도 처리한다.

```text
no abdominal pain, nausea, vomiting, chest pain, or difficulty breathing
```

위 문장의 listed mentions는 모두 negated로 본다. positive mention이 하나도
남지 않으면 row를 쓰지 않는다.

## Concept Refinement

raw MedCAT output에는 너무 일반적인 concept가 많이 잡힌다. 학습용 silver
label로 바로 쓰지 않도록 conservative cleanup을 적용한다.

항상 제거하는 positive concept:

```text
Disease
Infectious disease
Malignant neoplastic disease
```

더 긴 specific mention 안에 nested되어 있으면 제거하는 concept:

```text
Pain
Disease
Malignant neoplastic disease
Poisoning
```

예:

```text
right-sided chest pain
  keep: Right sided chest pain
  drop: Pain

skin cancer
  keep: Malignant neoplasm of skin
  drop: Malignant neoplastic disease

food poisoning
  keep: Food poisoning
  drop: Poisoning
```

이 정제 후 positive concept이 하나도 없으면 row를 쓰지 않는다.

## Output Schema

JSONL row는 sentence/statement 단위다.

```json
{
  "note_id": "synthetic-note-1",
  "subject_id": 1,
  "hadm_id": 10,
  "sentence_index": 0,
  "text": "The patient has pneumonia and reports chest pain.",
  "concept_ids": [111, 4329041],
  "concept_names": ["Pneumonia", "Pain"],
  "hard_negative_concept_ids": [],
  "hard_negative_concept_names": [],
  "mentions": [
    {
      "start": 16,
      "end": 25,
      "text": "pneumonia",
      "concept_id": 111,
      "concept_ids": [111],
      "concept_name": "Pneumonia",
      "confidence": 1.0,
      "negated": false,
      "assertion": "present"
    },
    {
      "start": 38,
      "end": 48,
      "text": "chest pain",
      "concept_id": 4329041,
      "concept_ids": [4329041],
      "concept_name": "Pain",
      "confidence": 1.0,
      "negated": false,
      "assertion": "present"
    }
  ],
  "hard_negative_mentions": [],
  "label_source": "medcat_omop_snomed_condition"
}
```

Hard-negative example:

```json
{
  "text": "She denies edema but has pneumonia.",
  "concept_ids": [111],
  "concept_names": ["Pneumonia"],
  "hard_negative_concept_ids": [433595],
  "hard_negative_concept_names": ["Edema"],
  "mentions": [
    {"text": "pneumonia", "concept_id": 111, "concept_name": "Pneumonia", "assertion": "present"}
  ],
  "hard_negative_mentions": [
    {"text": "edema", "concept_id": 433595, "concept_name": "Edema", "assertion": "negated"}
  ]
}
```

## 실행 방법

처음 CDB까지 만드는 smoke run:

```bash
python3 scripts/build_medcat_silver_dataset.py \
  --note-file data/01_raw/mimic-iv-note/2.2/note/discharge.csv.gz \
  --vocab-dir data/01_raw/vocabulary_v5 \
  --out-root data/03_processed/text_concept_dataset/medcat_silver_v1 \
  --build-cdb-path data/03_processed/text_concept_dataset/medcat_silver_v1/medcat_omop_snomed_condition_cdb \
  --max-notes 1000 \
  --min-sentence-words 6 \
  --max-sentences-per-note 20
```

기존 CDB 재사용:

```bash
python3 scripts/build_medcat_silver_dataset.py \
  --note-file data/01_raw/mimic-iv-note/2.2/note/discharge.csv.gz \
  --out-root data/03_processed/text_concept_dataset/medcat_silver_v1 \
  --cdb-path data/03_processed/text_concept_dataset/medcat_silver_v1/medcat_omop_snomed_condition_cdb \
  --max-notes 1000 \
  --min-sentence-words 6 \
  --max-sentences-per-note 20
```

전체 discharge note 실행은 `--max-notes 0`을 사용한다.

```bash
python3 scripts/build_medcat_silver_dataset.py \
  --note-file data/01_raw/mimic-iv-note/2.2/note/discharge.csv.gz \
  --out-root data/03_processed/text_concept_dataset/medcat_silver_full_v1 \
  --cdb-path data/03_processed/text_concept_dataset/medcat_silver_v1/medcat_omop_snomed_condition_cdb \
  --max-notes 0 \
  --min-sentence-words 6 \
  --max-sentences-per-note 20
```

## Current Runs

1,000-note refined subset:

| Metric | Value |
|---|---:|
| Source notes | `1,000` |
| Notes with mentions | `999` |
| Written rows | `6,731` |
| Unique positive concepts | `1,391` |
| Unique hard-negative concepts | `245` |
| Output size | `117M` directory / `5.8M` JSONL |

10,000-note dry-run:

| Metric | Value |
|---|---:|
| Runtime | `891.25s` / `14m 51s` |
| Source notes | `10,000` |
| Notes with mentions | `9,999` |
| Written rows | `67,674` |
| Unique positive concepts | `3,764` |
| Unique hard-negative concepts | `840` |
| Output JSONL size | `58M` |

Full discharge file:

| Metric | Value |
|---|---:|
| Discharge note rows | `331,793` |
| Notes with mentions | `331,792` |
| Written rows | `2,266,848` |
| Unique positive concepts | `11,629` |
| Unique hard-negative concepts | `3,725` |
| MedCAT version | `2.7.0` |
| JSONL size | about `2.0GB` |

Public aggregate manifest:

```bash
python3 scripts/make_medcat_silver_public_manifest.py \
  --summary-json data/03_processed/text_concept_dataset/medcat_silver_full_v1/reports/summary.json \
  --out docs/dataset/medcat_silver_full_v1_public_manifest.json
```

## Sanity Checks

After the latest refined generation:

```text
Disease positive rows: 0
Malignant neoplastic disease positive rows: 0
ADMISSION/DISCHARGE EXAM header rows: 0
inline ROS label leftovers: 0
```

Regression tests:

```bash
python3 -m pytest tests/medcat_silver_dataset_test.py tests/text_concept_dataset_test.py -q
```

Current result:

```text
21 passed in 1.45s
```

## 주의점

이 dataset은 gold가 아니라 silver다. MedCAT과 rule-based negation/splitting이
만든 자동 주석이므로 final benchmark로 쓰기보다 다음 용도에 맞다.

- mention-level silver supervised training
- admission weak pretrain 이후 silver finetune
- hard negative ablation
- manually verified sentence subset 생성 전 후보 pool

남은 주요 리스크:

- generic concept blocklist는 conservative v1이며 더 늘어날 수 있음
- long sentence/list row가 완전히 사라진 것은 아님
- pretrained MedCAT model pack과 비교 검증 필요
- final evaluation에는 manual sentence-level 검수 subset이 필요
