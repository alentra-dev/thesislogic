"""Gateway: FastAPI app serving the API and the attorney workspace UI."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import __version__, audit, auth, workflows
from .config import get_settings
from .db import app_db
from .ingestion import ingest_bytes, ocr_readiness
from .packs import Pack, list_packs, load_pack
from .providers import build_embedding_provider, build_generation_provider
from .retrieval import Retriever

settings = get_settings()
settings.ensure_dirs()
app = FastAPI(title="ThesisLogic", version=__version__)

_pack: Pack | None = None
_retriever: Retriever | None = None
_provider = None
_embedder = None


def get_db():
    return app_db(settings.data_dir)


def get_pack() -> Pack:
    global _pack, _retriever
    if _pack is None:
        pack_id = settings.active_pack
        if not pack_id:
            available = [p["pack_id"] for p in list_packs(settings.packs_dir) if not p.get("error")]
            if not available:
                raise HTTPException(503, "no jurisdiction pack installed; see docs/adoption-guide.md")
            pack_id = available[0]
        _pack = load_pack(settings.packs_dir, pack_id)
        if not _pack.index_path.exists():
            raise HTTPException(503, f"pack '{pack_id}' has no built index; run: thesislogic pack build {pack_id}")
        _retriever = Retriever(_pack, get_embedder())
    return _pack


def get_retriever() -> Retriever:
    get_pack()
    return _retriever


def get_provider():
    global _provider
    if _provider is None:
        _provider = build_generation_provider(settings)
    return _provider


def get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = build_embedding_provider(settings)
    return _embedder


def require_session(authorization: str = Header(default="")) -> dict:
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return auth.resolve_session(get_db(), token)
    except auth.AuthError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


# ------------------------------------------------------------------ models

class RegisterBody(BaseModel):
    user_id: str
    password: str
    display_name: str = ""


class SessionBody(BaseModel):
    user_id: str
    password: str
    matter_id: str = "general"


class PasswordBody(BaseModel):
    current_password: str
    new_password: str


class AdminResetBody(BaseModel):
    user_id: str
    new_password: str


class ResearchBody(BaseModel):
    question: str
    document_ids: list[str] = []


class DocumentsBody(BaseModel):
    document_ids: list[str]
    dimension: str = "deadlines"


class DraftBody(BaseModel):
    instructions: str
    document_type: str = ""
    style_profile_id: str = ""
    document_ids: list[str] = []


class StyleBody(BaseModel):
    name: str
    directives: list[str]
    scope: str = "private"
    status: str = "draft"


# ------------------------------------------------------------------ system

@app.get("/api/v1/health")
def health():
    pack_info = None
    try:
        pack = get_pack()
        pack_info = {"pack_id": pack.pack_id, "name": pack.name,
                     "jurisdiction": pack.jurisdiction,
                     "practice_areas": len(pack.practice_areas)}
    except HTTPException as exc:
        pack_info = {"error": exc.detail}
    embedder = get_embedder()
    return {
        "service": "thesislogic", "version": __version__, "firm": settings.firm_name,
        "pack": pack_info,
        "generation": get_provider().health(),
        "embedding": embedder.health() if embedder else {"provider": "none", "ready": True,
                                                         "detail": "lexical-only retrieval"},
        "ocr": ocr_readiness(),
        "posture": {"prefer_live_output": settings.prefer_live_output,
                    "provider": settings.generation_provider},
    }


@app.get("/api/v1/packs")
def packs():
    return {"packs": list_packs(settings.packs_dir), "active": settings.active_pack}


@app.get("/api/v1/practice-areas")
def practice_areas():
    pack = get_pack()
    return {"pack_id": pack.pack_id, "practice_areas": [
        {"id": pa.id, "name": pa.name, "keywords": pa.keywords,
         "description": pa.description, "official_sources": pa.official_sources}
        for pa in pack.practice_areas]}


# -------------------------------------------------------------------- auth

@app.post("/api/v1/auth/register")
def register(body: RegisterBody):
    if not settings.allow_registration:
        db = get_db()
        if db.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] > 0:
            raise HTTPException(403, "self-registration disabled; ask an admin")
    try:
        return auth.register_user(get_db(), body.user_id, body.password, body.display_name)
    except auth.AuthError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@app.post("/api/v1/auth/session")
def create_session(body: SessionBody):
    try:
        return auth.create_session(get_db(), body.user_id, body.password, body.matter_id,
                                   settings.session_ttl_seconds, settings.lockout_threshold,
                                   settings.lockout_seconds)
    except auth.AuthError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@app.post("/api/v1/auth/password")
def change_password(body: PasswordBody, session: dict = Depends(require_session),
                    authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()
    db = get_db()
    try:
        auth.change_password(db, session["user_id"], body.current_password,
                             body.new_password, keep_token=token)
    except auth.AuthError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    audit.record(db, audit.new_request_id(), "password_changed",
                 user_id=session["user_id"], matter_id=session["matter_id"])
    return {"status": "password_changed"}


@app.post("/api/v1/auth/admin-reset-password")
def admin_reset_password(body: AdminResetBody, session: dict = Depends(require_session)):
    if session["role"] != "admin":
        raise HTTPException(403, "admin role required")
    db = get_db()
    try:
        auth.admin_reset_password(db, body.user_id, body.new_password)
    except auth.AuthError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    audit.record(db, audit.new_request_id(), "password_admin_reset",
                 user_id=session["user_id"], detail={"target_user": body.user_id})
    return {"status": "password_reset", "user_id": body.user_id}


# ---------------------------------------------------------------- documents

def _load_documents(db, session: dict, document_ids: list[str]) -> list[dict]:
    docs = []
    for document_id in document_ids:
        row = db.execute(
            "SELECT * FROM documents WHERE document_id = ? AND matter_id = ?",
            (document_id, session["matter_id"])).fetchone()
        if row:
            docs.append({"document_id": row["document_id"], "filename": row["filename"],
                         "text": row["text"], "facts": json.loads(row["facts_json"])})
    return docs


@app.post("/api/v1/uploads")
async def upload(session: dict = Depends(require_session), files: list[UploadFile] = File(...)):
    db = get_db()
    request_id = audit.new_request_id()
    receipts = []
    for upload_file in files:
        payload = await upload_file.read()
        result = ingest_bytes(upload_file.filename or "upload", payload)
        if result.status == "extracted":
            db.execute(
                "INSERT INTO documents (document_id, matter_id, user_id, filename, "
                "extraction_path, status, text, facts_json) VALUES (?,?,?,?,?,?,?,?)",
                (result.document_id, session["matter_id"], session["user_id"], result.filename,
                 result.extraction_path, result.status, result.text,
                 json.dumps(result.facts or {})))
            db.commit()
        receipts.append({"document_id": result.document_id, "filename": result.filename,
                         "status": result.status, "extraction_path": result.extraction_path,
                         "detail": result.detail, "facts": result.facts})
        audit.record(db, request_id, "document_ingested", user_id=session["user_id"],
                     matter_id=session["matter_id"],
                     detail={"filename": result.filename, "status": result.status,
                             "extraction_path": result.extraction_path})
    return {"request_id": request_id, "receipts": receipts}


@app.get("/api/v1/documents")
def documents(session: dict = Depends(require_session)):
    rows = get_db().execute(
        "SELECT document_id, filename, extraction_path, status, created_at, user_id "
        "FROM documents WHERE matter_id = ? ORDER BY created_at DESC",
        (session["matter_id"],)).fetchall()
    return {"matter_id": session["matter_id"], "documents": [dict(r) for r in rows]}


@app.get("/api/v1/documents/{document_id}")
def document_detail(document_id: str, session: dict = Depends(require_session)):
    row = get_db().execute(
        "SELECT * FROM documents WHERE document_id = ? AND matter_id = ?",
        (document_id, session["matter_id"])).fetchone()
    if row is None:
        raise HTTPException(404, "document not found in this matter")
    return {"document_id": row["document_id"], "filename": row["filename"],
            "extraction_path": row["extraction_path"], "status": row["status"],
            "created_at": row["created_at"], "facts": json.loads(row["facts_json"]),
            "preview": row["text"][:2000]}


# ---------------------------------------------------------------- workflows

def _matter_context(docs: list[dict]) -> str:
    parts = []
    for doc in docs[:4]:
        parts.append(f"[{doc['filename']}] {doc['text'][:1500]}")
    return "\n\n".join(parts)


def _save_result(db, session: dict, request_id: str, result: workflows.WorkflowResult,
                 question: str = "") -> str:
    import uuid
    result_id = uuid.uuid4().hex[:12]
    payload = result.to_dict()
    payload["request_id"] = request_id
    db.execute(
        "INSERT INTO results (result_id, matter_id, user_id, workflow, question, payload_json) "
        "VALUES (?,?,?,?,?,?)",
        (result_id, session["matter_id"], session["user_id"], result.workflow, question,
         json.dumps(payload)))
    db.commit()
    return result_id


def _audit_workflow(db, session, request_id: str, result: workflows.WorkflowResult):
    audit.record(db, request_id, f"workflow_{result.workflow}",
                 user_id=session["user_id"], matter_id=session["matter_id"],
                 detail={"mode": result.mode,
                         "generation_state": result.generation.get("state", "deterministic_only"),
                         "provider": result.generation.get("provider", "none"),
                         "model": result.generation.get("model", ""),
                         "proof_passed": result.proof.get("passed"),
                         "citations": result.citations,
                         "retrieval": result.evidence.get("retrieval_audit", {})})


@app.post("/api/v1/workflows/research")
def run_research(body: ResearchBody, session: dict = Depends(require_session)):
    db = get_db()
    request_id = audit.new_request_id()
    docs = _load_documents(db, session, body.document_ids)
    result = workflows.research(body.question, get_pack(), get_retriever(),
                                get_provider(), settings, matter_context=_matter_context(docs))
    _audit_workflow(db, session, request_id, result)
    result_id = _save_result(db, session, request_id, result, body.question)
    return {"request_id": request_id, "result_id": result_id, **result.to_dict()}


@app.post("/api/v1/workflows/summary")
def run_summary(body: DocumentsBody, session: dict = Depends(require_session)):
    db = get_db()
    request_id = audit.new_request_id()
    docs = _load_documents(db, session, body.document_ids)
    if not docs:
        raise HTTPException(400, "no matter documents selected")
    result = workflows.summarize_documents(docs)
    _audit_workflow(db, session, request_id, result)
    result_id = _save_result(db, session, request_id, result)
    return {"request_id": request_id, "result_id": result_id, **result.to_dict()}


@app.post("/api/v1/workflows/chronology")
def run_chronology(body: DocumentsBody, session: dict = Depends(require_session)):
    db = get_db()
    request_id = audit.new_request_id()
    docs = _load_documents(db, session, body.document_ids)
    if not docs:
        raise HTTPException(400, "no matter documents selected")
    result = workflows.chronology(docs)
    _audit_workflow(db, session, request_id, result)
    result_id = _save_result(db, session, request_id, result)
    return {"request_id": request_id, "result_id": result_id, **result.to_dict()}


@app.post("/api/v1/workflows/compare")
def run_compare(body: DocumentsBody, session: dict = Depends(require_session)):
    db = get_db()
    request_id = audit.new_request_id()
    docs = _load_documents(db, session, body.document_ids)
    if len(docs) < 2:
        raise HTTPException(400, "compare requires at least two matter documents")
    result = workflows.compare(docs, body.dimension)
    _audit_workflow(db, session, request_id, result)
    result_id = _save_result(db, session, request_id, result)
    return {"request_id": request_id, "result_id": result_id, **result.to_dict()}


@app.post("/api/v1/workflows/privilege-review")
def run_privilege(body: DocumentsBody, session: dict = Depends(require_session)):
    db = get_db()
    request_id = audit.new_request_id()
    docs = _load_documents(db, session, body.document_ids)
    if not docs:
        raise HTTPException(400, "no matter documents selected")
    result = workflows.privilege_review(docs)
    _audit_workflow(db, session, request_id, result)
    result_id = _save_result(db, session, request_id, result)
    return {"request_id": request_id, "result_id": result_id, **result.to_dict()}


@app.post("/api/v1/workflows/draft")
def run_draft(body: DraftBody, session: dict = Depends(require_session)):
    db = get_db()
    request_id = audit.new_request_id()
    docs = _load_documents(db, session, body.document_ids)
    directives: list[str] = []
    if body.style_profile_id:
        row = db.execute("SELECT * FROM style_profiles WHERE profile_id = ?",
                         (body.style_profile_id,)).fetchone()
        if row and (row["owner_user_id"] == session["user_id"]
                    or (row["scope"] == "firm" and row["status"] == "published")):
            directives = json.loads(row["directives_json"])
    result = workflows.draft_document(body.instructions, body.document_type, get_pack(),
                                      get_retriever(), get_provider(), settings,
                                      style_directives=directives,
                                      matter_context=_matter_context(docs))
    _audit_workflow(db, session, request_id, result)
    result_id = _save_result(db, session, request_id, result, body.instructions)
    return {"request_id": request_id, "result_id": result_id, **result.to_dict()}


# ------------------------------------------------------------ saved results

@app.get("/api/v1/results")
def results(session: dict = Depends(require_session)):
    rows = get_db().execute(
        "SELECT result_id, workflow, question, created_at, user_id FROM results "
        "WHERE matter_id = ? ORDER BY created_at DESC LIMIT 50",
        (session["matter_id"],)).fetchall()
    return {"matter_id": session["matter_id"], "results": [dict(r) for r in rows]}


@app.get("/api/v1/results/{result_id}")
def result_detail(result_id: str, session: dict = Depends(require_session)):
    row = get_db().execute(
        "SELECT * FROM results WHERE result_id = ? AND matter_id = ?",
        (result_id, session["matter_id"])).fetchone()
    if row is None:
        raise HTTPException(404, "result not found in this matter")
    return {"result_id": row["result_id"], "workflow": row["workflow"],
            "question": row["question"], "created_at": row["created_at"],
            "payload": json.loads(row["payload_json"])}


# ------------------------------------------------------------ style profiles

@app.get("/api/v1/styles")
def styles(session: dict = Depends(require_session)):
    rows = get_db().execute(
        "SELECT * FROM style_profiles WHERE owner_user_id = ? "
        "OR (scope = 'firm' AND status = 'published') ORDER BY updated_at DESC",
        (session["user_id"],)).fetchall()
    return {"styles": [{"profile_id": r["profile_id"], "name": r["name"],
                        "scope": r["scope"], "status": r["status"],
                        "owner": r["owner_user_id"],
                        "directives": json.loads(r["directives_json"])} for r in rows]}


@app.post("/api/v1/styles")
def create_style(body: StyleBody, session: dict = Depends(require_session)):
    import uuid
    if body.scope == "firm" and session["role"] != "admin":
        raise HTTPException(403, "only admins can create firm-shared style profiles")
    profile_id = uuid.uuid4().hex[:12]
    get_db().execute(
        "INSERT INTO style_profiles (profile_id, name, owner_user_id, scope, status, directives_json) "
        "VALUES (?,?,?,?,?,?)",
        (profile_id, body.name, session["user_id"], body.scope,
         body.status if body.scope == "firm" else "published",
         json.dumps(body.directives)))
    get_db().commit()
    return {"profile_id": profile_id}


# ------------------------------------------------------------------ audit

@app.get("/api/v1/audit")
def audit_log(session: dict = Depends(require_session), request_id: str = "", limit: int = 100):
    return {"events": audit.query(get_db(), matter_id=session["matter_id"],
                                  request_id=request_id, limit=limit)}


# --------------------------------------------------------------------- UI

@app.get("/", response_class=HTMLResponse)
def workspace():
    ui_path = Path(__file__).parent / "ui" / "workspace.html"
    html = ui_path.read_text()
    return HTMLResponse(html.replace("__FIRM_NAME__", settings.firm_name)
                        .replace("__VERSION__", __version__))


@app.exception_handler(Exception)
async def unhandled(_, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})
