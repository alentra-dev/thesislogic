"""Deterministic document intake.

Extraction order (VLM-free by design):
  - .txt/.md: decoded in-process
  - digital PDF: pdftotext
  - scanned PDF: ocrmypdf + pdftotext (when installed)
  - images: tesseract (when installed)

Unsupported types fail explicitly — never a silent stub. Every ingested
document also gets a deterministic fact sheet (dates, deadlines, monetary
amounts, governing-law sentences, privilege indicators) that downstream
workflows reuse without a model call.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".text"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}

_DATE = re.compile(
    r"\b(?:(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})\b")
_DEADLINE = re.compile(
    r"[^.\n]*\b(deadline|due (?:on|by|date)|no later than|within \d+ days|on or before|"
    r"must (?:be )?(?:file|serve|respond|submit)\w*)\b[^.\n]*", re.I)
_MONEY = re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?")
_GOVERNING_LAW = re.compile(
    r"[^.\n]*\b(governing law|governed by|construed (?:under|in accordance with)|"
    r"laws of the state of|jurisdiction and venue)\b[^.\n]*", re.I)
_PRIVILEGE = re.compile(
    r"\b(attorney[- ]client|privileged|work product|confidential communication|"
    r"legal advice|settlement negotiation|prepared in anticipation of litigation)\b", re.I)


@dataclass
class IngestResult:
    document_id: str
    filename: str
    status: str            # extracted | failed
    extraction_path: str   # text | pdf_text | pdf_ocr | image_ocr | unsupported
    text: str = ""
    detail: str = ""
    facts: dict | None = None


def _tool(name: str) -> str | None:
    return shutil.which(name)


def ocr_readiness() -> dict:
    return {
        "pdftotext": bool(_tool("pdftotext")),
        "ocrmypdf": bool(_tool("ocrmypdf")),
        "tesseract": bool(_tool("tesseract")),
        "scanned_pdf_ready": bool(_tool("ocrmypdf")) and bool(_tool("pdftotext")),
        "image_ocr_ready": bool(_tool("tesseract")),
    }


def extract_facts(text: str) -> dict:
    dates = list(dict.fromkeys(_DATE.findall(text)))[:40]
    deadlines = [m.group(0).strip() for m in _DEADLINE.finditer(text)][:20]
    amounts = list(dict.fromkeys(_MONEY.findall(text)))[:30]
    governing = [m.group(0).strip() for m in _GOVERNING_LAW.finditer(text)][:10]
    privilege = list(dict.fromkeys(m.group(0).lower() for m in _PRIVILEGE.finditer(text)))[:10]
    return {
        "dates": dates,
        "deadline_sentences": deadlines,
        "monetary_amounts": amounts,
        "governing_law_sentences": governing,
        "privilege_indicators": privilege,
        "characters": len(text),
    }


def _pdf_text(path: Path) -> str:
    result = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                            capture_output=True, text=True, timeout=120)
    return result.stdout if result.returncode == 0 else ""


def ingest_bytes(filename: str, payload: bytes) -> IngestResult:
    document_id = uuid.uuid4().hex[:12]
    suffix = Path(filename).suffix.lower()

    if suffix in TEXT_SUFFIXES:
        try:
            text = payload.decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001 - report, never crash intake
            return IngestResult(document_id, filename, "failed", "text", detail=str(exc))
        return IngestResult(document_id, filename, "extracted", "text", text=text,
                            facts=extract_facts(text))

    if suffix == ".pdf":
        if not _tool("pdftotext"):
            return IngestResult(document_id, filename, "failed", "unsupported",
                                detail="pdftotext is not installed (poppler-utils)")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(payload)
            tmp_path = Path(tmp.name)
        try:
            text = _pdf_text(tmp_path)
            if len(text.strip()) >= 40:
                return IngestResult(document_id, filename, "extracted", "pdf_text",
                                    text=text, facts=extract_facts(text))
            if not _tool("ocrmypdf"):
                return IngestResult(document_id, filename, "failed", "pdf_ocr",
                                    detail="scanned PDF requires ocrmypdf, which is not installed")
            ocr_path = tmp_path.with_suffix(".ocr.pdf")
            proc = subprocess.run(
                ["ocrmypdf", "--skip-text", "--quiet", str(tmp_path), str(ocr_path)],
                capture_output=True, text=True, timeout=600)
            if proc.returncode != 0:
                return IngestResult(document_id, filename, "failed", "pdf_ocr",
                                    detail=f"ocrmypdf failed: {proc.stderr[:300]}")
            text = _pdf_text(ocr_path)
            ocr_path.unlink(missing_ok=True)
            if len(text.strip()) < 20:
                return IngestResult(document_id, filename, "failed", "pdf_ocr",
                                    detail="OCR produced no usable text")
            return IngestResult(document_id, filename, "extracted", "pdf_ocr",
                                text=text, facts=extract_facts(text))
        finally:
            tmp_path.unlink(missing_ok=True)

    if suffix in IMAGE_SUFFIXES:
        if not _tool("tesseract"):
            return IngestResult(document_id, filename, "failed", "image_ocr",
                                detail="image OCR requires tesseract, which is not installed")
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(payload)
            tmp_path = Path(tmp.name)
        try:
            proc = subprocess.run(["tesseract", str(tmp_path), "-"],
                                  capture_output=True, text=True, timeout=300)
            text = proc.stdout
            if proc.returncode != 0 or len(text.strip()) < 5:
                return IngestResult(document_id, filename, "failed", "image_ocr",
                                    detail="tesseract produced no usable text")
            return IngestResult(document_id, filename, "extracted", "image_ocr",
                                text=text, facts=extract_facts(text))
        finally:
            tmp_path.unlink(missing_ok=True)

    return IngestResult(document_id, filename, "failed", "unsupported",
                        detail=f"unsupported_file_type: {suffix or '(none)'}")
