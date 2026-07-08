# Changelog

## 0.3.0 — 2026-07-08

### Added
- **OpenAI cloud provider** (`THESISLOGIC_GENERATION_PROVIDER=openai`): api.openai.com with
  sensible defaults (`gpt-4o`, `OPENAI_API_KEY`), no extra package. Also available for
  embeddings (`THESISLOGIC_EMBEDDING_PROVIDER=openai`, default `text-embedding-3-small`).
- **Google Gemini cloud provider** (`THESISLOGIC_GENERATION_PROVIDER=gemini`): native
  Generative Language API over HTTPS, no SDK dependency; default `gemini-2.5-pro`;
  key via `GEMINI_API_KEY`/`GOOGLE_API_KEY`.
- Live health probes for all cloud providers via `thesislogic doctor` and `/api/v1/health`.

### Notes
- The proof gate, retrieval-confidence floor, and audit trail treat every provider
  identically; adding vendors changes procurement options, never safety posture.

## 0.2.0 — 2026-07-06

### Added
- Attorney-grade output: full memorandum structure for research (Question Presented / Brief
  Answer / Governing Law with verbatim quotations / Application / Practice Notes / Unresolved
  Points); filing-shaped drafting (caption, numbered paragraphs, prayer for relief).
- Citation-integrity footer on every research/draft answer.
- Proof-gate feedback retry: rejected drafts get one corrective regeneration naming the exact
  unverified citations.
- Retrieval-confidence floor: generation is withheld (with a visible LOW-confidence caution)
  when no authority is citation/name-anchored and per-authority question coverage is weak.
- Generation prompt character budget for small local context windows.
- Password management: self-service change (UI + API, revokes other sessions), admin reset
  (`thesislogic user passwd` + API), audit events for both.
- Markdown rendering in the workspace (dependency-free, escaped) and per-result markdown
  export with provenance headers.
- Validation prompt suite (`docs/validation-prompts.md`) with 22 automated checks.

### Fixed
- FTS index now covers full authority text (operative statute language past 4,000 characters
  was previously unsearchable); field-weighted BM25 ranks citation/title hits above body term
  frequency; guaranteed statute/rule slots on doctrinal questions.
- Exact-citation lookup tolerates prefix variants (`§ 452.340` finds `RSMo 452.340`);
  fixed a word-boundary bug that prevented `§` patterns from matching at all.
- Citations quoted inside validated support spans count as grounded in the proof gate.

## 0.1.0 — 2026-07-06

Initial release: jurisdiction packs, typed evidence-package retrieval, cite-or-decline proof
gate, deterministic-first workflows (research, draft, summary, chronology, compare, privilege
review), matter-isolated auth, append-only audit trail, local/Anthropic/no-model providers,
attorney workspace UI, adoption guide, comprehensive legal disclaimer.
