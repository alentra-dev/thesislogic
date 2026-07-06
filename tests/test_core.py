"""Core behavior tests: packs, retrieval, proof gate, workflows, auth."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from thesislogic import auth, proofgate, workflows
from thesislogic.config import Settings
from thesislogic.db import app_db
from thesislogic.ingestion import extract_facts, ingest_bytes
from thesislogic.packs import build_index, derive_spans, load_pack, scaffold_pack
from thesislogic.providers.base import GenerationResult
from thesislogic.retrieval import Retriever


@pytest.fixture()
def pack(tmp_path: Path):
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    scaffold_pack(packs_dir, "teststate", "Test State", "Test State")
    records = [
        {"authority_type": "case", "citation": "915 S.W.2d 372",
         "title": "Woolridge v. Woolridge", "court": "Test State Court of Appeals",
         "jurisdiction": "Test State", "year": 1996, "aliases": ["Woolridge v. Woolridge"],
         "topic_labels": ["family_law"],
         "text": "We hold that child support must be calculated using the presumed amount. "
                 "The trial court must consider Rule 88.01 in every child support case. "
                 "This appeal arises from a dissolution of marriage proceeding."},
        {"authority_type": "statute", "citation": "§ 452.330",
         "title": "Disposition of marital property", "court": "",
         "jurisdiction": "Test State", "year": 2020, "aliases": [],
         "topic_labels": ["family_law"],
         "text": "The court shall divide marital property in such proportions as the court "
                 "deems just after considering all relevant factors."},
    ]
    source = packs_dir / "teststate" / "authorities.ndjson"
    source.write_text("\n".join(json.dumps(r) for r in records))
    p = load_pack(packs_dir, "teststate")
    build_index(p, progress_every=0)
    return p


def test_pack_build_and_exact_lookup(pack):
    retriever = Retriever(pack)
    evidence = retriever.retrieve("What does 915 S.W.2d 372 say about child support?")
    assert evidence.authorities
    assert evidence.authorities[0]["match_basis"] == "exact_citation"
    assert "915 S.W.2d 372" in evidence.allowed_citations


def test_alias_lookup(pack):
    retriever = Retriever(pack)
    evidence = retriever.retrieve("Explain Woolridge v. Woolridge on presumed support")
    assert any(a["title"] == "Woolridge v. Woolridge" for a in evidence.authorities)


def test_lexical_retrieval_and_spans(pack):
    retriever = Retriever(pack)
    evidence = retriever.retrieve("How is marital property divided?")
    assert any(a["citation"] == "§ 452.330" for a in evidence.authorities)
    assert evidence.spans


def test_proofgate_rejects_hallucinated_citation(pack):
    retriever = Retriever(pack)
    evidence = retriever.retrieve("child support presumed amount")
    answer = "Under 915 S.W.2d 372 the amount is presumed. See also 123 F.3d 456 (made up)."
    proof = proofgate.validate(answer, evidence, pack)
    assert not proof.passed
    assert any("123 F.3d 456" in c for c in proof.unverified_citations)


def test_proofgate_passes_verified_answer(pack):
    retriever = Retriever(pack)
    evidence = retriever.retrieve("child support presumed amount 915 S.W.2d 372")
    answer = "Under 915 S.W.2d 372, the presumed amount governs child support."
    proof = proofgate.validate(answer, evidence, pack)
    assert proof.passed
    assert proof.verified_citations


def test_research_downgrades_on_bad_model_output(pack):
    class HallucinatingProvider:
        name = "test"

        def generate(self, system, prompt, max_tokens=1600):
            return GenerationResult(text="Per 999 U.S. 999, you win.", provider="test",
                                    model="test-model", live=True)

        def health(self):
            return {"provider": "test", "ready": True}

    settings = Settings()
    settings.prefer_live_output = True
    result = workflows.research("child support presumed amount", pack,
                                Retriever(pack), HallucinatingProvider(), settings)
    assert result.mode == "deterministic"
    assert result.generation["state"] == "downgraded_to_deterministic"


def test_research_promotes_good_model_output(pack):
    class GroundedProvider:
        name = "test"

        def generate(self, system, prompt, max_tokens=1600):
            return GenerationResult(
                text="Short Answer: the presumed amount governs. See 915 S.W.2d 372.",
                provider="test", model="test-model", live=True)

        def health(self):
            return {"provider": "test", "ready": True}

    settings = Settings()
    settings.prefer_live_output = True
    result = workflows.research("child support presumed amount 915 S.W.2d 372", pack,
                                Retriever(pack), GroundedProvider(), settings)
    assert result.mode == "live"
    assert result.generation["state"] == "live_promoted"


def test_research_declines_without_evidence(pack):
    settings = Settings()
    result = workflows.research("quantum cryptocurrency airspace treaty", pack,
                                Retriever(pack),
                                __import__("thesislogic.providers.deterministic",
                                           fromlist=["DeterministicProvider"]).DeterministicProvider(),
                                settings)
    assert "do not establish" in result.answer or result.evidence["authorities"] == []


def test_derive_spans_excludes_captions():
    text = ("IN THE COURT OF APPEALS OF TEST STATE this caption should not be support. "
            "We hold that the judgment is affirmed because the record supports it fully.")
    spans = derive_spans(text)
    caption = [s for s in spans if s["span_type"] == "caption"]
    holdings = [s for s in spans if s["span_type"] == "holding"]
    assert all(not s["support_eligible"] for s in caption)
    assert holdings and holdings[0]["support_eligible"]


def test_deterministic_workflows():
    doc = {"filename": "contract.txt",
           "text": "This Agreement is governed by the laws of the State of Test. "
                   "Payment of $5,000.00 is due on January 15, 2026. "
                   "Any response must be filed within 30 days. "
                   "This letter contains attorney-client privileged legal advice.",
           "facts": None}
    doc["facts"] = extract_facts(doc["text"])
    assert "January 15, 2026" in doc["facts"]["dates"]

    chron = workflows.chronology([doc])
    assert "January 15, 2026" in chron.answer

    comp = workflows.compare([doc, dict(doc, filename="contract2.txt")], "governing_law")
    assert "governed by the laws" in comp.answer

    priv = workflows.privilege_review([doc])
    assert "REVIEW" in priv.answer

    summary = workflows.summarize_documents([doc])
    assert "contract.txt" in summary.answer


def test_ingest_text_and_unsupported():
    ok = ingest_bytes("note.txt", b"Deadline: response due on or before March 3, 2026.")
    assert ok.status == "extracted"
    assert ok.facts["deadline_sentences"]
    bad = ingest_bytes("evil.exe", b"\x00\x01")
    assert bad.status == "failed"
    assert "unsupported_file_type" in bad.detail


def test_auth_lifecycle(tmp_path: Path):
    db = app_db(tmp_path)
    user = auth.register_user(db, "alice", "correct-horse-battery", "Alice")
    assert user["role"] == "admin"  # first user becomes admin
    session = auth.create_session(db, "alice", "correct-horse-battery", "matter-1",
                                  ttl_seconds=3600, lockout_threshold=3, lockout_seconds=60)
    resolved = auth.resolve_session(db, session["token"])
    assert resolved["matter_id"] == "matter-1"
    with pytest.raises(auth.AuthError):
        auth.create_session(db, "alice", "wrong", "matter-1", 3600, 3, 60)
    with pytest.raises(auth.AuthError):
        auth.resolve_session(db, "bogus-token")


def test_proofgate_accepts_span_grounded_citation(pack):
    retriever = Retriever(pack)
    evidence = retriever.retrieve("child support presumed amount 915 S.W.2d 372")
    # "Rule 88.01" is not an authority record, but appears inside a validated span.
    answer = "Per 915 S.W.2d 372, the court must consider Rule 88.01 in every case."
    proof = proofgate.validate(answer, evidence, pack)
    assert proof.passed, proof.warnings
    assert any("88.01" in c for c in proof.verified_citations)


def test_full_text_indexing_finds_deep_statute_language(tmp_path: Path):
    """Operative language buried past 4000 chars must still be searchable."""
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    scaffold_pack(packs_dir, "deep", "Deep", "Deep State")
    filler = "This subsection addresses administrative matters of no relevance. " * 80
    assert len(filler) > 4500
    record = {"authority_type": "statute", "citation": "RSMo 452.340",
              "title": "Child support — payments may be made directly to child, when",
              "jurisdiction": "Deep State", "year": 2020, "aliases": [], "topic_labels": [],
              "text": filler + " The court may order that payments be made directly to the "
                               "child if the child is enrolled in an institution of higher education."}
    (packs_dir / "deep" / "authorities.ndjson").write_text(json.dumps(record) + "\n")
    p = load_pack(packs_dir, "deep")
    build_index(p, progress_every=0)
    ev = Retriever(p).retrieve("when may payments be made directly to the child enrolled in higher education")
    assert any("452.340" in a["citation"] for a in ev.authorities)


def test_exact_lookup_prefix_fallback(pack):
    """'section 452.330' must find the record stored as '§ 452.330'."""
    ev = Retriever(pack).retrieve("What does section 452.330 say?")
    hits = [(a["citation"], a["match_basis"]) for a in ev.authorities]
    assert ("§ 452.330", "exact_citation") in hits, hits


def test_title_weighting_beats_body_frequency(tmp_path: Path):
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    scaffold_pack(packs_dir, "weight", "Weight", "Weight State")
    records = [
        {"authority_type": "case", "citation": "1 W.S. 1", "title": "Noise v. Noise",
         "jurisdiction": "Weight State", "year": 2000, "aliases": [], "topic_labels": [],
         "text": ("The garnishment procedure was discussed. " * 60)},
        {"authority_type": "statute", "citation": "WS 100.1",
         "title": "Garnishment procedure — exemptions",
         "jurisdiction": "Weight State", "year": 2020, "aliases": [], "topic_labels": [],
         "text": "A garnishment shall not attach to exempt wages."},
    ]
    (packs_dir / "weight" / "authorities.ndjson").write_text(
        "\n".join(json.dumps(r) for r in records))
    p = load_pack(packs_dir, "weight")
    build_index(p, progress_every=0)
    ev = Retriever(p).retrieve("When does the law allow garnishment exemptions?")
    assert ev.authorities[0]["citation"] == "WS 100.1", [a["citation"] for a in ev.authorities]


def test_password_change_and_admin_reset(tmp_path: Path):
    db = app_db(tmp_path)
    auth.register_user(db, "bob", "original-password-1", "Bob")
    s1 = auth.create_session(db, "bob", "original-password-1", "m1", 3600, 3, 60)
    s2 = auth.create_session(db, "bob", "original-password-1", "m2", 3600, 3, 60)
    with pytest.raises(auth.AuthError):
        auth.change_password(db, "bob", "wrong-current", "new-password-123", s1["token"])
    auth.change_password(db, "bob", "original-password-1", "new-password-123", s1["token"])
    assert auth.resolve_session(db, s1["token"])["user_id"] == "bob"  # caller survives
    with pytest.raises(auth.AuthError):
        auth.resolve_session(db, s2["token"])  # other sessions revoked
    auth.create_session(db, "bob", "new-password-123", "m1", 3600, 3, 60)
    auth.admin_reset_password(db, "bob", "admin-set-password-9")
    auth.create_session(db, "bob", "admin-set-password-9", "m1", 3600, 3, 60)


def test_gate_feedback_retry_recovers(pack):
    """First draft hallucinates; corrective retry produces a grounded draft."""
    class FlakyProvider:
        name = "test"
        calls = 0

        def generate(self, system, prompt, max_tokens=1600):
            FlakyProvider.calls += 1
            if FlakyProvider.calls == 1:
                return GenerationResult(text="See 999 U.S. 999 (fabricated).",
                                        provider="test", model="t", live=True)
            assert "REJECTED" in prompt and "999 U.S. 999" in prompt
            return GenerationResult(text="The presumed amount governs. See 915 S.W.2d 372.",
                                    provider="test", model="t", live=True)

        def health(self):
            return {"provider": "test", "ready": True}

    settings = Settings()
    settings.prefer_live_output = True
    settings.generation_gate_retries = 1
    result = workflows.research("child support presumed amount 915 S.W.2d 372", pack,
                                Retriever(pack), FlakyProvider(), settings)
    assert result.mode == "live"
    assert result.generation["attempts"] == 2
    assert result.generation["retry_feedback"]


def test_generation_prompt_respects_budget(pack):
    from thesislogic.workflows import _generation_prompt
    evidence = Retriever(pack).retrieve("child support presumed amount")
    _, small = _generation_prompt(evidence, pack, "task", budget=200)
    _, large = _generation_prompt(evidence, pack, "task", budget=20000)
    assert len(small) < len(large) or evidence.spans == []
    assert "ALLOWED CITATIONS" in small
