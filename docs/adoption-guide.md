# Adoption Guide: bringing ThesisLogic to *your* jurisdiction, practice, and firm

ThesisLogic ships jurisdiction-neutral. Everything specific to where and how you practice lives
in three layers you populate once and then maintain:

1. a **jurisdiction pack** (authorities + citation formats + disclaimers),
2. a **practice-area registry** (routing taxonomy inside the pack),
3. **firm style profiles** (writing directives, managed in the app).

This guide walks a deploying firm through all three, in order. Budget roughly: an afternoon for a
pilot pack with a sampled corpus; longer for a complete authority corpus depending on your sources.

---

## Step 1 — Scaffold your jurisdiction pack

```bash
thesislogic pack scaffold missouri --name "Missouri" --jurisdiction "Missouri"
```

This creates `packs/missouri/` with four files:

| File | What you put in it |
|---|---|
| `pack.json` | name, citation regex patterns, disclaimer text, prompt overlay |
| `practice_areas.json` | your jurisdiction's practice-area taxonomy (Step 3) |
| `authorities.sample.ndjson` | replace with `authorities.ndjson` — your corpus (Step 2) |
| `README.md` | notes for your own team |

Multiple packs can coexist (e.g. `missouri` + `federal-8th-circuit`); set the active one with
`THESISLOGIC_ACTIVE_PACK`.

### Tune the citation patterns

`pack.json` → `citation_patterns` is a list of regexes describing what a citation *looks like*
in your jurisdiction. These drive both exact-citation retrieval and — critically — the proof
gate's citation extraction. The scaffold ships sane US defaults (reporter citations, `§` sections,
`Rule N`). Add your jurisdiction's reporters and statute formats, e.g. for Missouri:

```json
"citation_patterns": [
  "\\b\\d{1,4}\\s+S\\.?W\\.?\\s?(?:2d|3d)\\s+\\d{1,5}\\b",
  "\\b(?:§|[Ss]ection)\\s*\\d{1,3}\\.\\d+\\b",
  "\\b[Rr]ule\\s+\\d{1,3}\\.\\d+\\b",
  "\\bRSMo\\b[^,.]{0,20}"
]
```

Test them: run a research query citing a known authority and confirm it appears as an
`exact_citation` hit in the answer-provenance rail.

## Step 2 — Import your authority corpus

The pack index is built from `authorities.ndjson` — one JSON object per line:

```json
{"authority_type": "case", "citation": "915 S.W.2d 372", "title": "Woolridge v. Woolridge",
 "court": "Missouri Court of Appeals", "jurisdiction": "Missouri", "year": 1996,
 "aliases": ["Woolridge v. Woolridge"], "topic_labels": ["family_law"],
 "text": "full opinion text ..."}
```

**Where to get authority data (US examples, all free):**

- **Case law:** [CourtListener / Free Law Project](https://www.courtlistener.com/help/api/) bulk
  data exports per court; map `citation`, `case_name` → `title`, `plain_text` → `text`.
- **Statutes:** most states publish revisor XML/HTML you can scrape into one record per section;
  set `authority_type: "statute"` and put the section number in `citation`.
- **Court rules:** state court websites; `authority_type: "rule"`.
- **Ethics opinions, local rules, standing orders:** your bar association and district sites.

Then build the index:

```bash
thesislogic pack build missouri            # full corpus
thesislogic pack build missouri --limit 5000   # sampled pilot
```

The builder creates an FTS5 lexical index and segments each authority into typed proposition
spans (holdings, rule statements, procedural statements). If your source data already has curated
spans, include a `spans` array on each record and it is used verbatim — curated spans beat the
heuristic segmentation and are worth the investment for your most-cited authorities.

**Optional semantic retrieval:** if you run an embedding server (llama.cpp with an embedding
model, Ollama, etc.):

```bash
export THESISLOGIC_EMBEDDING_PROVIDER=openai_compatible
export THESISLOGIC_EMBEDDING_BASE_URL=http://127.0.0.1:8092
thesislogic pack embed missouri
```

Retrieval blends semantic candidates with lexical ones before ranking. Without embeddings,
ThesisLogic runs lexical-only — fully functional, just less tolerant of vocabulary mismatch.

**Scale note:** the current semantic blend is dependency-free pure Python and is recommended for
packs up to roughly 10,000 authorities (or a curated high-value subset). For larger corpora, run
lexical-only — exact-citation, alias, and BM25 retrieval carry the workload well — or embed only
your most-cited authorities. A vector-index backend is on the roadmap.

## Step 3 — Define your practice areas

`practice_areas.json` routes questions to the right doctrinal neighborhood and shows attorneys
which practice signals the system detected. Anchor each area to your **official bar taxonomy**
(state bar committees/sections) so the registry is defensible, and give each one routing keywords:

```json
{"practice_areas": [
  {"id": "family_law", "name": "Family Law", "priority": 110,
   "keywords": ["child support", "custody", "dissolution", "maintenance", "marital property"],
   "description": "Domestic relations under your state's dissolution statutes.",
   "official_sources": [{"source_name": "Your State Bar", "title": "Family Law Section",
                          "url": "https://..."}]}
]}
```

Lower `priority` numbers rank first on keyword ties. Ten to twenty areas with 8–15 keywords each
is the sweet spot; overlapping keywords are fine — areas are ranked, not exclusive.

## Step 4 — Choose your AI posture

| Posture | Configuration | When |
|---|---|---|
| **Local AI** | `GENERATION_PROVIDER=openai_compatible` + a llama.cpp/Ollama/vLLM server | client confidentiality requires data on-premises |
| **Cloud AI — Claude** | `GENERATION_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` | firm accepts a cloud DPA; no GPU hardware |
| **Cloud AI — OpenAI** | `GENERATION_PROVIDER=openai` + `OPENAI_API_KEY` | same, OpenAI procurement |
| **Cloud AI — Gemini** | `GENERATION_PROVIDER=gemini` + `GEMINI_API_KEY` | same, Google procurement |
| **No AI** | `GENERATION_PROVIDER=none` | deterministic-only environments |

The proof gate, retrieval-confidence floor, and audit trail behave identically under every
posture — switching providers never changes the safety guarantees, only who runs the model.

Two additional dials:

- `THESISLOGIC_PREFER_LIVE_OUTPUT=false` runs every model in **shadow mode**: attorneys always
  see the deterministic answer, and live output is recorded in the audit trail for evaluation.
  Recommended for the first weeks of any deployment.
- `thesislogic doctor` verifies the whole chain before you let attorneys in.

## Step 5 — Encode your firm's style

Style profiles are writing directives applied to drafting — the one layer that is deliberately
cross-matter (style is not case knowledge). Create them in the workspace or via
`POST /api/v1/styles`:

```json
{"name": "Firm litigation style", "scope": "firm", "status": "published",
 "directives": [
   "Use active voice; no sentence over 30 words.",
   "Cite per local rules: full cite on first use, short cite after.",
   "Headings: Roman numerals for arguments, letters for sub-points.",
   "Never use 'clearly' or 'obviously'."
 ]}
```

Only admins publish firm-scoped profiles; private profiles are per-attorney. Directives are
injected into drafting prompts and listed on the deterministic draft skeleton, so they apply in
both modes.

## Step 6 — Validate before go-live

1. `thesislogic doctor` — everything green.
2. Ask five research questions with **known** answers in your jurisdiction; confirm the expected
   authorities appear and the proof gate shows `passed`.
3. Ask one question your corpus **cannot** answer; confirm the system declines rather than
   inventing support.
4. Upload a scanned PDF; confirm the extraction path shows `pdf_ocr` and the chronology workflow
   finds its dates.
5. Create two matters and confirm documents from one never surface in the other.
6. Review `GET /api/v1/audit` and confirm every test run is fully reconstructable.

## Maintaining your installation

- **Corpus refresh:** re-run `pack build` on an updated `authorities.ndjson`; the index is
  rebuilt atomically. Re-run `pack embed` afterwards if you use semantic retrieval.
- **New practice areas / keywords:** edit `practice_areas.json`; changes load on restart.
- **Multiple jurisdictions:** one pack per jurisdiction; run one instance per pack or switch
  `THESISLOGIC_ACTIVE_PACK` per deployment.
- **Audit retention:** `data/app.sqlite3` holds the audit trail; back it up on your firm's
  document-retention schedule.
