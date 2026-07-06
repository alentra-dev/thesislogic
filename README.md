# ThesisLogic

**Open-source, proof-gated legal AI workbench — for any jurisdiction, any practice area, any firm.**

ThesisLogic is a self-hostable legal AI application built around one uncompromising idea:
**no generative output leaves the system with an unverified citation.** Recent US cases have
shown what happens when AI-drafted filings cite authorities that do not exist. ThesisLogic is
designed so that failure mode is structurally impossible, while still giving attorneys the
speed of a modern AI workbench.

## Why ThesisLogic is different

1. **Proof gate (cite-or-decline).** Every AI-generated answer is parsed for citations, and each
   citation is verified against the validated authority index for your jurisdiction. Unverifiable
   citations cause an automatic, visible downgrade to the deterministic answer. The system prefers
   *"the retrieved authorities do not establish that proposition"* over a polished hallucination.
2. **Typed evidence packages, not raw chunks.** Retrieval returns authority records and
   support-eligible proposition spans (holdings, rule statements) — never anonymous text chunks.
   Generation may only quote from that package. Case captions are stored but never accepted as
   substantive support.
3. **Deterministic first, generative second.** Document summary, chronology, compare, and
   privilege review are fully deterministic — no model call in the common path. Research and
   drafting always build a deterministic answer first; a live model may replace it only after
   passing the proof gate.
4. **Local AI or cloud AI — your choice per deployment.**
   - `openai_compatible`: any local server speaking the OpenAI API (llama.cpp, Ollama, vLLM,
     LM Studio) — case data never leaves your hardware;
   - `anthropic`: Claude via the official API for firms that prefer managed cloud models;
   - `none`: zero-model deterministic mode — every workflow still works.
5. **Jurisdiction packs.** All jurisdiction-specific knowledge (authorities, citation formats,
   practice-area taxonomy, disclaimers, prompt overlays) lives in a data pack, not in code.
   Scaffold a pack for any US state (or any legal system) in minutes and load your own corpus.
6. **Matter isolation.** Documents, results, and context are scoped to `user + matter`. Knowledge
   never crosses matters just because they share a practice area.
7. **Full audit trail.** Every answer records: request id, provider, model, retrieval candidate mix,
   the evidence package, proof-gate outcome, and whether live output was shadowed or downgraded.
   The workspace shows this provenance next to every answer.

## Quick start

```bash
git clone https://github.com/alentra-dev/thesislogic
cd thesislogic
python3 -m venv .venv && . .venv/bin/activate
pip install -e .

# 1. create a jurisdiction pack (or drop in a prebuilt one)
thesislogic pack scaffold my-state --name "My State" --jurisdiction "My State"
#    ... replace packs/my-state/authorities.sample.ndjson with authorities.ndjson ...
thesislogic pack build my-state

# 2. choose your AI posture (fully optional — 'none' is a first-class mode)
export THESISLOGIC_GENERATION_PROVIDER=openai_compatible   # llama.cpp / Ollama / vLLM
export THESISLOGIC_GENERATION_BASE_URL=http://127.0.0.1:8080
export THESISLOGIC_GENERATION_MODEL=your-model
# or: THESISLOGIC_GENERATION_PROVIDER=anthropic  + ANTHROPIC_API_KEY (pip install 'thesislogic[anthropic]')

# 3. run
thesislogic doctor      # verify packs, providers, OCR tooling
thesislogic serve       # workspace at http://127.0.0.1:8600
```

Register the first user from the login screen — it automatically becomes the admin.

## Documentation

- [docs/adoption-guide.md](docs/adoption-guide.md) — **start here**: migrate your jurisdiction(s),
  practice area(s), and firm style into your own installation
- [docs/architecture.md](docs/architecture.md) — system design and the proof-gate pipeline
- [docs/deployment.md](docs/deployment.md) — production deployment (systemd, local models, HTTPS)
- [docs/responsible-ai.md](docs/responsible-ai.md) — best practices for AI in regulated legal work

## Workflows

| Workflow | Path | AI involvement |
|---|---|---|
| Research memo | question → evidence package → memo | deterministic memo always; live model only if proof gate passes |
| Draft document | instructions + firm style + authority anchors | same proof-gated promotion |
| Summarize | frequency-ranked extractive summary | none |
| Chronology | deterministic date extraction + sort | none |
| Compare | deadlines / governing law / dates / amounts | none |
| Privilege review | conservative lexical indicators, review-only | none |

## Requirements

- Python 3.11+
- Optional for PDF/OCR intake: `poppler-utils` (pdftotext), `ocrmypdf`, `tesseract-ocr`
- Optional for local AI: any OpenAI-compatible model server
- Optional for cloud AI: `pip install 'thesislogic[anthropic]'` + `ANTHROPIC_API_KEY`

## Author & License

Created by **Udonna Eke-Okoro** ([@alentra-dev](https://github.com/alentra-dev)).

Apache-2.0 — provided **as is**, with no warranty of any kind. ThesisLogic is a tool for licensed
professionals: it does not provide legal advice, creates no attorney–client relationship, and
every output requires attorney review before reliance or filing. Deployers are solely responsible
for their corpus, their model providers, and their professional-responsibility compliance.
**Read [DISCLAIMER.md](DISCLAIMER.md) before deploying.**
