# Responsible AI in Legal Practice — how ThesisLogic operationalizes it

Courts across the US have sanctioned filings containing AI-fabricated citations, and bar
associations now issue guidance on generative AI competence (see ABA Formal Opinion 512 and
state-bar equivalents). ThesisLogic's design treats those obligations as engineering
requirements, not disclaimers. This document maps professional duties to the mechanisms that
enforce them, and lists the practices a deploying firm still owns.

## Duty → mechanism

| Professional duty | ThesisLogic mechanism |
|---|---|
| Candor to the tribunal — no false authority | **Proof gate**: every generative citation must resolve to a validated record in the jurisdiction pack; otherwise the answer is downgraded and the attempt logged |
| Competence with technology | **Provenance rail**: every answer displays mode (deterministic vs live), model, retrieval mix, and proof outcome — attorneys always know what they are reading |
| Confidentiality | **Local-AI posture**: fully on-premises operation with llama.cpp/Ollama; cloud APIs are an explicit opt-in; no telemetry |
| Supervision of nonlawyer assistance (AI as assistant) | **Shadow mode** for evaluation periods; professional-review notice on every output; review-only privilege flags |
| Client-file integrity | **Matter isolation**: strict user+matter scoping enforced server-side from the session token |
| Recordkeeping / accountability | **Append-only audit trail** keyed by request id, reconstructable per matter |

## Deployment practices we recommend (firm-owned)

1. **Start in shadow mode.** Run `THESISLOGIC_PREFER_LIVE_OUTPUT=false` for the first weeks.
   Attorneys get deterministic answers; the audit trail accumulates live-model candidates you can
   review before promoting live output.
2. **Verify the corpus, not just the model.** The proof gate is only as good as the pack. Validate
   your authority import against known questions (adoption guide, Step 6) and re-run after every
   corpus refresh.
3. **Keep humans on the signature line.** ThesisLogic labels every output as AI-assisted work
   product requiring attorney review. Make that review a documented step in your filing workflow.
4. **Write down your AI policy.** Which matters may use cloud AI, who may publish firm style
   profiles, who reviews the audit log, and on what retention schedule.
5. **Do not disable the gate.** There is intentionally no configuration flag that lets unverified
   citations through. If you fork the project, preserve that property.

## What ThesisLogic does *not* do, by design

- No judge/outcome prediction and no analytics on individual judges.
- No general-purpose chatbot mode: every interaction is a scoped workflow with a defined
  evidence basis.
- No generative OCR: intake is deterministic (pdftotext/ocrmypdf/tesseract), so extracted text is
  reproducible evidence, not a model's interpretation.
- No silent behavior: unsupported files fail loudly, model failures surface in the provenance
  rail, and downgrades are visible to the attorney — never smoothed over.
