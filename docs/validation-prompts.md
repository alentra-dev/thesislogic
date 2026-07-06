# Validation Prompt Suite

Run these after installing a jurisdiction pack, after every corpus refresh, and after changing
providers. Each prompt tests a specific failure mode. The Missouri examples in brackets show how
to adapt them; substitute equivalents from **your** jurisdiction with answers you already know.

## Research workflow

| # | Prompt pattern | What it validates | Expected behavior |
|---|---|---|---|
| R1 | Ask a question whose controlling authority you know *[Missouri: "What is the standard of review for court-tried cases under Murphy v. Carron?"]* | case-name (alias) retrieval + span quality | the named case is retrieved via `alias`; its holding spans appear |
| R2 | Ask a doctrinal "when does the law allow…" question answered by a statute, phrased **without** the statute's own vocabulary *[Missouri: "For children older than 18 enrolled in college, when can support be paid directly to the child instead of the spouse?" → RSMo 452.340]* | vocabulary-mismatch retrieval; statute vs case ranking | the controlling statute appears in the evidence package |
| R3 | Cite a real authority by citation string *["What does 536 S.W.2d 30 hold?"]* | exact-citation lookup | `exact_citation` match basis, score 100 |
| R4 | Cite a statute using a different prefix form than the corpus stores *["What does § 452.340 provide?" when the corpus stores "RSMo 452.340"]* | citation normalization fallback | still an `exact_citation` match |
| R5 | Ask about a **fabricated** authority *["Explain the holding of Smith v. Vortex, 999 S.W.4th 1 (Mo. 2025)"]* | hallucination bait | no invented explanation: the fake cite is never "verified"; answer is deterministic/declining |
| R6 | Ask something your corpus cannot answer *["What are maritime salvage rights for asteroid mining vessels under Missouri law?"]* | cite-or-decline | deterministic mode; no live promotion; weak matches visibly labeled |
| R7 | Re-ask R1 with a live provider configured | proof-gate promotion | `mode: live`, `proof.passed: true`, all citations verified |
| R8 | Ask R1 with the model server stopped | provider failure handling | answer still returned (deterministic); `backend_unavailable` in provenance |

## Document workflows

Create two test files first:

**`engagement.txt`** — "Engagement letter dated March 5, 2024. A responsive pleading must be
filed no later than April 30, 2024. Fee of $12,500.00. This communication contains
attorney-client privileged legal advice. This Agreement is governed by the laws of the State of
Missouri."

**`contract.txt`** — "Services Agreement dated 2024-02-10. Payment of $8,000.00 due within 30
days of invoice. Governed by the laws of the State of Kansas. Deliverables due on or before
June 1, 2024."

| # | Action | Expected behavior |
|---|---|---|
| D1 | Upload both files | receipts show `extracted` / `text`; fact sheets list dates, deadlines, amounts |
| D2 | Upload a scanned PDF and an unsupported type (`.xyz`) | `pdf_ocr` path (or explicit OCR-missing failure); `unsupported_file_type` — never a silent stub |
| D3 | Chronology on both | all four dates, sorted, each with source attribution |
| D4 | Compare on `governing_law` | Missouri vs Kansas clauses side by side |
| D5 | Compare on `deadlines` | the two deadline sentences extracted per document |
| D6 | Privilege review on both | `engagement.txt` flagged REVIEW with indicators; `contract.txt` clean; advisory language present |
| D7 | Summary on both | extractive bullets per document, no invented content |
| D8 | Log into a **different matter** and list documents | uploads from the first matter are invisible (isolation) |

## Drafting workflow

| # | Prompt | Expected behavior |
|---|---|---|
| DR1 | "Draft a motion to modify child support based on a substantial and continuing change of circumstances." | authority anchors from the pack; every legal proposition cited; `[BRACKETED PLACEHOLDERS]` for unknown facts |
| DR2 | Same, with a firm style profile selected | style directives visibly applied / listed |
| DR3 | Draft on a topic with no corpus support | anchors section declines rather than inventing authority |

## System checks

| # | Check | Expected |
|---|---|---|
| S1 | `GET /api/v1/audit` after the runs above | every workflow present with provider/model/proof/downgrade detail |
| S2 | Change password, then reuse an old session token from another browser | old token rejected |
| S3 | 5 wrong passwords in a row | account temporarily locked (423) |
| S4 | `thesislogic doctor` | pack built, provider ready, OCR status accurate |

Record the results with the date and corpus version; re-run after every `pack build`.
