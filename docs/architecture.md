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

1. **Retrieve.** Exact citation lookup (with prefix-tolerant fallback, so `§ 452.340` finds
   `RSMo 452.340`) → alias lookup → field-weighted full-text BM25 (citation and title hits
   outrank body term frequency; full authority text is indexed) → optional semantic blend.
   Doctrinal questions get guaranteed statute/rule slots. Output is an *evidence package*:
   ranked authority records, their support-eligible spans, and the allowed-citation set.
   Captions/boilerplate spans are never support-eligible.
2. **Confidence floor.** The retriever measures per-authority question coverage. If no authority
   matched by citation or case name and the best single authority covers < 45% of the question's
   vocabulary, the package is marked not proof-ready: generation is withheld, the memo carries a
   plain-language LOW-confidence caution, and the skip is audited. A verified citation to an
   unresponsive authority is still a wrong answer — this closes that gap.
3. **Deterministic answer.** A complete memorandum/draft skeleton — grouped by authority
   hierarchy with quoted support language — is always built from the evidence package alone. If
   nothing was retrieved, the answer is a structured decline, not an apology.
4. **Generate (optional).** If a provider is configured, the model writes under a *citation
   contract*: the allowed-citation list stated at both edges of the prompt, exact-string rules,
   and approved decline language. The evidence section respects a character budget
   (`THESISLOGIC_GENERATION_PROMPT_BUDGET`) so small local context windows never cause backend
   errors. Matter context is included as untrusted data only.
5. **Gate.** Every citation-shaped string in the candidate is extracted using the pack's citation
   patterns plus generic patterns, and verified against the allowed set (citations quoted inside
   validated spans also count as grounded). On failure the model gets one corrective retry naming
   the exact unverified citations (`THESISLOGIC_GENERATION_GATE_RETRIES`); if it still fails, the
   deterministic answer is returned and the downgrade is recorded and displayed. Passing answers
   carry a citation-integrity footer stating what was verified.
6. **Audit.** Request id, provider, model, retrieval mix, coverage, attempts, proof outcome, and
   gate decision are written to the append-only audit log and rendered in the workspace
   provenance rail.

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

`thesislogic/providers/` defines two small protocols (generation, embeddings) with these
implementations: `deterministic` (none), `openai_compat` (every local OpenAI-compatible server,
and cloud OpenAI via the `openai` alias with `api.openai.com` defaults), `gemini` (Google
Generative Language API over plain HTTPS, no SDK), and `anthropic` (official SDK, optional
extra). API keys come from `THESISLOGIC_GENERATION_API_KEY` or each vendor's conventional
variable. Providers must never raise into workflows; failures surface as `backend_unavailable`
in the audit trail and answers fall back to deterministic mode automatically. The gate and
confidence floor treat every provider identically — model choice is a procurement decision, not
a safety one.

## Security posture

- uploaded documents are treated as untrusted data; their text is labeled as such in prompts and
  never interpreted as instructions;
- passwords are PBKDF2-hashed; sessions expire; failed logins trigger lockout;
- no telemetry, no external calls except the configured model endpoints;
- deterministic OCR (pdftotext/ocrmypdf/tesseract) — no vision model in the intake path.
