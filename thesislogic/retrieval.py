"""Typed retrieval: evidence packages, never raw chunks.

Retrieval never returns an answer. It returns an EvidencePackage — the ranked
authority records, their support-eligible proposition spans, and the exact set
of citations any downstream generation is allowed to use. Query order:

    1. exact citation lookup (pack citation patterns found in the question)
    2. alias/title lookup
    3. FTS5 BM25 lexical search
    4. optional semantic blend (when an embedding provider is configured)
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass, field

from .packs import Pack, normalize_citation
from .providers.base import EmbeddingProvider

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'\-]+")
_DOCTRINAL = re.compile(
    r"\b(when (?:does|may|must|is|can)|what does the (?:law|statute)|allow(?:s|ed)?|"
    r"require(?:s|d)?|is it (?:legal|permitted)|under what circumstances)\b", re.I)
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "are", "was", "were", "what",
    "when", "where", "who", "how", "does", "can", "under", "about", "law",
    "legal", "case", "cases", "any", "all", "not", "may", "must", "shall",
    "than", "then", "instead", "also", "only", "such", "more", "most", "they",
    "them", "their", "there", "these", "those", "will", "would", "could",
    "should", "upon", "into", "from", "have", "has", "had", "been", "being",
    "which", "whether", "other", "each", "between", "because", "after", "before",
}


@dataclass
class EvidencePackage:
    question: str
    workflow: str
    authorities: list[dict] = field(default_factory=list)
    spans: list[dict] = field(default_factory=list)
    allowed_citations: list[str] = field(default_factory=list)
    practice_areas: list[str] = field(default_factory=list)
    retrieval_audit: dict = field(default_factory=dict)
    # False when retrieval matched only on scattered vocabulary: a verified
    # citation to an unresponsive authority is still a wrong answer, so live
    # generation is withheld unless the evidence is actually about the question.
    proof_ready: bool = True

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "workflow": self.workflow,
            "authorities": self.authorities,
            "spans": self.spans,
            "allowed_citations": self.allowed_citations,
            "practice_areas": self.practice_areas,
            "retrieval_audit": self.retrieval_audit,
            "proof_ready": self.proof_ready,
        }


def _row_to_authority(row: sqlite3.Row, match_basis: str, score: float = 0.0) -> dict:
    return {
        "authority_id": row["authority_id"],
        "authority_type": row["authority_type"],
        "citation": row["citation"],
        "title": row["title"],
        "court": row["court"],
        "jurisdiction": row["jurisdiction"],
        "year": row["year"],
        "topic_labels": json.loads(row["topic_labels_json"]),
        "excerpt": row["text_excerpt"][:400],
        "match_basis": match_basis,
        "score": round(score, 4),
    }


def _fts_query(question: str) -> str:
    tokens = [t.lower() for t in _WORD.findall(question) if len(t) > 2 and t.lower() not in _STOPWORDS]
    seen: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.append(t)
    return " OR ".join(f'"{t}"' for t in seen[:16])


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


class Retriever:
    def __init__(self, pack: Pack, embedder: EmbeddingProvider | None = None):
        self.pack = pack
        self.embedder = embedder

    def _exact_lookup(self, db: sqlite3.Connection, question: str) -> list[dict]:
        found: list[dict] = []
        seen: set[str] = set()
        for regex in self.pack.citation_regexes():
            for match in regex.finditer(question):
                norm = normalize_citation(match.group(0))
                if norm in seen:
                    continue
                seen.add(norm)
                row = db.execute(
                    "SELECT * FROM authorities WHERE normalized_citation = ?", (norm,)).fetchone()
                if row is None:
                    # Prefix-tolerant fallback: "§ 452.340" must find "RSMo 452.340".
                    core = re.sub(r"^[^\d]+", "", norm).strip()
                    if len(core) >= 5:
                        row = db.execute(
                            "SELECT * FROM authorities WHERE normalized_citation LIKE ? "
                            "ORDER BY length(normalized_citation) LIMIT 1",
                            (f"%{core}",)).fetchone()
                if row:
                    found.append(_row_to_authority(row, "exact_citation", 100.0))
        return found

    def _alias_lookup(self, db: sqlite3.Connection, question: str) -> list[dict]:
        """Match 'Name v. Name' style references against titles/aliases."""
        found: list[dict] = []
        for match in re.finditer(r"\b([A-Z][\w'\-]+)\s+v\.?\s+([A-Z][\w'\-]+)\b", question):
            needle = f"{match.group(1)} v. {match.group(2)}"
            rows = db.execute(
                "SELECT * FROM authorities WHERE title LIKE ? OR aliases_json LIKE ? LIMIT 3",
                (f"%{needle}%", f"%{needle}%")).fetchall()
            for row in rows:
                found.append(_row_to_authority(row, "alias", 90.0))
        return found

    def _lexical_search(self, db: sqlite3.Connection, question: str, limit: int) -> list[dict]:
        query = _fts_query(question)
        if not query:
            return []
        # Field-weighted BM25: a hit in the citation or title (which for
        # statutes usually states the doctrine) outranks body term frequency,
        # so a short on-point section beats a long opinion that merely repeats
        # the query vocabulary. Column order: authority_id, citation, title,
        # aliases, topics, body.
        rows = db.execute(
            "SELECT a.*, bm25(authorities_fts, 0.0, 12.0, 10.0, 6.0, 4.0, 1.0) AS rank "
            "FROM authorities_fts f "
            "JOIN authorities a ON a.authority_id = f.authority_id "
            "WHERE authorities_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit)).fetchall()
        doctrinal = _DOCTRINAL.search(question) is not None
        out = []
        for r in rows:
            score = -r["rank"]
            if doctrinal and r["authority_type"] in ("statute", "rule", "regulation"):
                score *= 1.3  # primary written law first for "when/what does the law" questions
            out.append(_row_to_authority(r, "lexical_bm25", score))
        out.sort(key=lambda a: -a["score"])
        return out

    def _semantic_search(self, db: sqlite3.Connection, question: str, limit: int) -> list[dict]:
        if self.embedder is None:
            return []
        has_vectors = db.execute("SELECT COUNT(*) AS n FROM embeddings").fetchone()["n"]
        if not has_vectors:
            return []
        vectors = self.embedder.embed([question])
        if not vectors:
            return []
        qvec = vectors[0]
        scored: list[tuple[float, str]] = []
        for row in db.execute("SELECT authority_id, vector_json FROM embeddings"):
            score = _cosine(qvec, json.loads(row["vector_json"]))
            scored.append((score, row["authority_id"]))
        scored.sort(reverse=True)
        out = []
        for score, authority_id in scored[:limit]:
            row = db.execute("SELECT * FROM authorities WHERE authority_id = ?", (authority_id,)).fetchone()
            if row:
                out.append(_row_to_authority(row, "semantic", score))
        return out

    def _spans_for(self, db: sqlite3.Connection, authority_ids: list[str],
                   question: str, per_authority: int = 4) -> list[dict]:
        tokens = {t.lower() for t in _WORD.findall(question) if t.lower() not in _STOPWORDS}
        spans: list[dict] = []
        seen_text: set[str] = set()
        for authority_id in authority_ids:
            rows = db.execute(
                "SELECT * FROM spans WHERE authority_id = ? AND support_eligible = 1 "
                "ORDER BY position LIMIT 60", (authority_id,)).fetchall()
            scored = []
            for row in rows:
                overlap = sum(1 for t in _WORD.findall(row["span_text"]) if t.lower() in tokens)
                type_bonus = {"holding": 3, "rule_statement": 2}.get(row["span_type"], 0)
                scored.append((overlap + type_bonus, row))
            scored.sort(key=lambda t: -t[0])
            kept = 0
            for score, row in scored:
                fingerprint = re.sub(r"\W+", "", row["span_text"].lower())[:90]
                if fingerprint in seen_text:
                    continue
                seen_text.add(fingerprint)
                spans.append({
                    "span_id": row["span_id"],
                    "authority_id": row["authority_id"],
                    "span_text": row["span_text"],
                    "span_type": row["span_type"],
                    "relevance": score,
                })
                kept += 1
                if kept >= per_authority:
                    break
        return spans

    def retrieve(self, question: str, workflow: str = "research",
                 context_text: str = "", max_authorities: int = 8) -> EvidencePackage:
        db = self.pack.db()
        practice_areas = [pa.name for pa in self.pack.match_practice_areas(question + " " + context_text)][:3]

        exact = self._exact_lookup(db, question)
        aliases = self._alias_lookup(db, question)
        lexical = self._lexical_search(db, question, limit=max_authorities * 8)
        semantic = self._semantic_search(db, question, limit=max_authorities)

        merged: dict[str, dict] = {}
        for bucket in (exact, aliases, lexical, semantic):
            for authority in bucket:
                existing = merged.get(authority["authority_id"])
                if existing is None or authority["score"] > existing["score"]:
                    merged[authority["authority_id"]] = authority
        pool = sorted(merged.values(), key=lambda a: -a["score"])
        ranked = pool[:max_authorities]

        # Doctrinal questions get guaranteed primary-written-law slots: in a
        # large corpus, term-frequency matches from long opinions can crowd
        # the controlling statute or rule out of the top ranks entirely.
        if _DOCTRINAL.search(question):
            in_top = sum(1 for a in ranked if a["authority_type"] in ("statute", "rule", "regulation"))
            reserves = [a for a in pool[max_authorities:]
                        if a["authority_type"] in ("statute", "rule", "regulation")]
            while in_top < 2 and reserves:
                # replace the lowest-ranked case with the best remaining statute
                for idx in range(len(ranked) - 1, -1, -1):
                    if ranked[idx]["authority_type"] not in ("statute", "rule", "regulation"):
                        ranked[idx] = reserves.pop(0)
                        in_top += 1
                        break
                else:
                    break
            ranked.sort(key=lambda a: -a["score"])

        spans = self._spans_for(db, [a["authority_id"] for a in ranked], question)
        allowed = [a["citation"] for a in ranked if a["citation"]]

        # Question-term coverage: what fraction of the question's content
        # vocabulary actually appears in the retrieved evidence. Low coverage
        # with no citation/name match means the corpus has nothing responsive.
        qtokens = {t.lower() for t in _WORD.findall(question)
                   if len(t) > 3 and t.lower() not in _STOPWORDS}
        evidence_text = " ".join(
            [s["span_text"] for s in spans] + [a["title"] + " " + a["excerpt"] for a in ranked]
        ).lower()
        coverage = (sum(1 for t in qtokens if t in evidence_text) / len(qtokens)) if qtokens else 0.0
        anchored = bool(exact or aliases)
        proof_ready = bool(ranked) and (anchored or coverage >= 0.45)

        return EvidencePackage(
            question=question,
            workflow=workflow,
            authorities=ranked,
            spans=spans,
            allowed_citations=allowed,
            practice_areas=practice_areas,
            retrieval_audit={
                "pack": self.pack.pack_id,
                "candidates": {"exact": len(exact), "alias": len(aliases),
                               "lexical": len(lexical), "semantic": len(semantic)},
                "semantic_active": bool(semantic),
                "promoted": len(ranked),
                "question_coverage": round(coverage, 3),
                "anchored": anchored,
            },
            proof_ready=proof_ready,
        )
