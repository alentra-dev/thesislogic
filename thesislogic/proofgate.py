"""The proof gate: cite-or-decline enforcement.

No generative output leaves ThesisLogic without passing through this gate.
It extracts every citation-like string from a candidate answer and verifies
each one against the evidence package's allowed-citation set. If the model
cited an authority that was not retrieved and validated — the classic
hallucinated-citation failure that has produced sanctions in US courts —
the answer is rejected and the workflow falls back to its deterministic
output, with the rejection recorded in the audit trail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .packs import Pack, normalize_citation
from .retrieval import EvidencePackage

# Generic patterns catch citation shapes even when a pack's own patterns
# are narrow, so a hallucinated federal citation in a state pack still fails.
_GENERIC_PATTERNS = [
    re.compile(r"\b\d{1,4}\s+[A-Z][A-Za-z.]*\.?\s?(?:2d|3d|4th|5th)?\s+\d{1,5}\b"),
    re.compile(r"\b\d{1,3}\s+U\.?S\.?C?\.?\s+§*\s*\d+\b"),
]

DECLINE_LANGUAGE = (
    "The retrieved authorities do not establish that proposition on the current "
    "record. No citation is offered rather than an unverified one."
)


@dataclass
class ProofResult:
    passed: bool
    verified_citations: list[str] = field(default_factory=list)
    unverified_citations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "verified_citations": self.verified_citations,
            "unverified_citations": self.unverified_citations,
            "warnings": self.warnings,
        }


def extract_citations(text: str, pack: Pack | None = None) -> list[str]:
    patterns = list(_GENERIC_PATTERNS)
    if pack is not None:
        patterns = pack.citation_regexes() + patterns
    found: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in pattern.finditer(text):
            norm = normalize_citation(match.group(0))
            if norm not in seen:
                seen.add(norm)
                found.append(match.group(0).strip())
    return found


def validate(answer: str, evidence: EvidencePackage, pack: Pack | None = None) -> ProofResult:
    """Validate a candidate answer against its evidence package."""
    warnings: list[str] = []
    if not answer.strip():
        return ProofResult(passed=False, warnings=["candidate answer is empty"])

    allowed = {normalize_citation(c) for c in evidence.allowed_citations}
    # Citations quoted inside validated support spans are grounded too: when a
    # retrieved holding says "child support ... in accordance with Rule 88.01",
    # the model may cite Rule 88.01 even though the rule itself is not a
    # separate authority record in the corpus.
    grounded_text = normalize_citation(" ".join(
        [span.get("span_text", "") for span in evidence.spans]
        + [a.get("excerpt", "") for a in evidence.authorities]))
    cited = extract_citations(answer, pack)
    verified, unverified = [], []
    for citation in cited:
        norm = normalize_citation(citation)
        # Section/rule fragments of allowed citations also count ("§ 452.330"
        # inside "Mo. Rev. Stat. § 452.330").
        ok = (norm in allowed or any(norm in a or a in norm for a in allowed)
              or (len(norm) >= 6 and norm in grounded_text))
        (verified if ok else unverified).append(citation)

    if unverified:
        warnings.append(
            f"answer cites {len(unverified)} authorit{'y' if len(unverified) == 1 else 'ies'} "
            f"outside the validated evidence package: {', '.join(unverified[:5])}")
    if evidence.authorities and not cited:
        warnings.append("answer contains no citations despite retrieved authorities")
    if not evidence.authorities:
        warnings.append("no authorities were retrieved; generative output cannot be grounded")

    passed = not unverified and (bool(verified) or not evidence.authorities)
    if not evidence.authorities:
        passed = False
    return ProofResult(passed=passed, verified_citations=verified,
                       unverified_citations=unverified, warnings=warnings)


def gate_decision(proof: ProofResult, prefer_live: bool) -> dict:
    """Decide whether live output may replace the deterministic answer."""
    if not prefer_live:
        return {"use_live": False, "reason": "live output shadowed by configuration"}
    if proof.passed:
        return {"use_live": True, "reason": "proof gate passed"}
    return {"use_live": False,
            "reason": "downgraded to deterministic output: " + "; ".join(proof.warnings[:3])}
