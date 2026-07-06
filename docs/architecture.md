# Architecture

ThesisLogic is a single deployable Python service (FastAPI) with SQLite storage, plus optional
external model servers. The simplicity is deliberate: a law firm's IT generalist should be able
to run, back up, and audit it.

```
                       ┌──────────────────────────────────────────────┐
   attorney browser ──▶│  Gateway (FastAPI)                           │
   (workspace UI)      │  auth · matters · uploads · workflows · audit│
                       └──────┬───────────────┬───────────────┬───────┘
                              │               │               │
                    ┌─────────▼──────┐ ┌──────▼───────┐ ┌─────▼─────────┐
                    │ Ingestion      │ │ Retrieval    │ │ Workflow      │
                    │ txt/md/pdf/OCR │ │ evidence     │ │ engine        │
                    │ + fact sheets  │ │ packages     │ │ det-first     │
                    └────────────────┘ └──────┬───────┘ └─────┬─────────┘
                                              │               │
                       ┌──────────────────────▼───┐   ┌───────▼────────────┐
                       │ Jurisdiction pack        │   │ Providers          │
                       │ authorities.sqlite3      │   │ none | local | API │
                       │ FTS5 + spans + vectors   │   └───────┬────────────┘
                       └──────────────────────────┘           │
                                                      ┌───────▼────────┐
                                                      │  PROOF GATE    │
                                                      │ cite-or-decline│
                                                      └────────────────┘
```

## The proof-gate pipeline (research & drafting)

1. **Retrieve.** Exact citation lookup → alias lookup → FTS5 BM25 → optional semantic blend.
   Output is an *evidence package*: ranked authority records, their support-eligible spans, and
   the allowed-citation set. Captions/boilerplate spans are never support-eligible.
2. **Deterministic answer.** A complete memo/draft skeleton is always built from the evidence
   package alone. If nothing was retrieved, the answer is a structured decline, not an apology.
3. **Generate (optional).** If a provider is configured, the model receives *only* the evidence
   package (plus scoped matter context marked as untrusted data) and the allowed-citation list.
4. **Gate.** Every citation-shaped string in the candidate is extracted using the pack's citation
   patterns plus generic patterns, and verified against the allowed set. Any unverified citation →
   the candidate is rejected, the deterministic answer is returned, and the downgrade is recorded
   and displayed.
5. **Audit.** Request id, provider, model, retrieval mix, proof outcome, and gate decision are
   written to the append-only audit log and rendered in the workspace provenance rail.

## Data model

- `packs/<id>/authorities.sqlite3` — `authorities` (typed records, normalized citations),
  `authorities_fts` (FTS5), `spans` (typed propositions with `support_eligible`),
  `embeddings` (optional vectors).
- `data/app.sqlite3` — `users`, `sessions` (TTL, matter-scoped), `matters`, `matter_members`,
  `documents` (extracted text + deterministic fact sheets), `results` (saved outputs with full
  provenance payloads), `style_profiles`, `audit_events`.

## Matter isolation

Protected routes derive `user_id`/`matter_id` from the bearer session — caller-supplied IDs are
ignored. Documents and results queries are always filtered by the session's matter. The only
cross-matter asset is the firm style profile, which holds writing directives, never case facts.

## Provider abstraction

`thesislogic/providers/` defines two small protocols (generation, embeddings) with three
implementations: `deterministic` (none), `openai_compat` (every local server + OpenAI-compatible
clouds), and `anthropic` (official SDK, optional extra). Providers must never raise into
workflows; failures surface as `backend_unavailable` in the audit trail and answers fall back to
deterministic mode automatically.

## Security posture

- uploaded documents are treated as untrusted data; their text is labeled as such in prompts and
  never interpreted as instructions;
- passwords are PBKDF2-hashed; sessions expire; failed logins trigger lockout;
- no telemetry, no external calls except the configured model endpoints;
- deterministic OCR (pdftotext/ocrmypdf/tesseract) — no vision model in the intake path.
