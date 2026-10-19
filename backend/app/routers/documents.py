import hashlib
from datetime import date
from pathlib import PurePath
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..db import get_db
from ..deps import current_user
from ..models import CvParse, Document, User, utcnow
from ..ratelimit import limit_user
from ..schemas import ConfirmCv, ProfileIO
from ..services import cv_parser, storage, uploads
from .profile import _out, get_profile

router = APIRouter(tags=["documents"])


def _doc_out(d: Document) -> dict:
    return {"id": d.id, "document_type": d.document_type, "filename": d.original_filename, "mime_type": d.mime_type,
            "size_bytes": d.size_bytes, "checksum": d.checksum, "scan_status": d.scan_status,
            "parsing_status": d.parsing_status, "created_at": d.created_at}


def _owned_doc(db: Session, user: User, doc_id: UUID) -> Document:
    d = db.get(Document, doc_id)
    if d is None or d.user_id != user.id:
        raise HTTPException(404, "Document not found")
    return d


def _parse_out(p: CvParse) -> dict:
    return {"parse_id": p.id, "document_id": p.document_id, "status": p.status, "parser_version": p.parser_version,
            "parsed": p.parsed_json, "flags": p.flags_json, "created_at": p.created_at,
            "notice": "Draft only. Nothing here is part of your profile until you confirm it."}


@router.post("/documents/upload", status_code=201,
             dependencies=[limit_user("upload", "rate_limit_upload")])
async def upload(file: UploadFile = File(...), document_type: str = Form("cv"),
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    if document_type != "cv":
        raise HTTPException(422, "Only document_type=cv is supported")
    # Read at most limit+1 bytes so an oversized body is rejected without buffering all of it.
    data = await file.read(settings.max_upload_bytes + 1)
    name = PurePath((file.filename or "").replace("\\", "/")).name[:255] or "upload"
    try:
        valid = uploads.validate(name, data)
        scan_status = uploads.scan(data)
    except uploads.UploadRejected as exc:
        audit(db, user.id, "upload_rejected", "document", reason=exc.message[:80])
        db.commit()
        raise HTTPException(exc.status_code, exc.message)
    key = storage.save(data)
    doc = Document(user_id=user.id, document_type=document_type, original_filename=name, storage_key=key,
                   mime_type=valid.mime, size_bytes=len(data), checksum=hashlib.sha256(data).hexdigest(),
                   scan_status=scan_status)
    db.add(doc)
    try:
        audit(db, user.id, "document_uploaded", "document", doc.id, scan_status=scan_status, kind=valid.kind)
        db.commit()
    except BaseException:
        storage.delete(key)  # don't orphan the file if the row cannot be committed
        raise
    return _doc_out(doc)


@router.get("/documents")
def list_documents(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [_doc_out(d) for d in db.scalars(
        select(Document).where(Document.user_id == user.id).order_by(Document.created_at.desc()))]


@router.get("/documents/{doc_id}")
def get_document(doc_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _doc_out(_owned_doc(db, user, doc_id))


@router.get("/documents/{doc_id}/download")
def download(doc_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = _owned_doc(db, user, doc_id)
    try:
        body = storage.read(d.storage_key)
    except FileNotFoundError:
        raise HTTPException(410, "Stored file is missing")
    safe = "".join(c for c in d.original_filename if c.isalnum() or c in "._- ") or "cv"
    return Response(body, media_type=d.mime_type, headers={
        "Content-Disposition": f'attachment; filename="{safe}"', "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store"})


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = _owned_doc(db, user, doc_id)
    key = d.storage_key
    audit(db, user.id, "document_deleted", "document", d.id)
    db.delete(d)
    db.commit()
    storage.delete(key)


@router.post("/documents/{doc_id}/parse")
def parse_document(doc_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Extract text and produce a *draft* parse. The profile is not touched."""
    d = _owned_doc(db, user, doc_id)
    kind = "pdf" if d.mime_type == uploads.MIME["pdf"] else "docx"
    try:
        text = cv_parser.extract_text(kind, storage.read(d.storage_key))
    except cv_parser.Unreadable as exc:
        d.parsing_status = "unreadable"
        db.commit()
        raise HTTPException(422, {"detail": str(exc), "parsing_status": "unreadable"})
    except FileNotFoundError:
        raise HTTPException(410, "Stored file is missing")
    try:
        parsed, flags = cv_parser.parse_text(text, date.today())
    except Exception:  # a parser bug must never become a 500 with document content in the trace
        d.parsing_status = "failed"
        db.commit()
        raise HTTPException(422, {"detail": "Parsing failed; please enter your details manually.",
                                  "parsing_status": "failed"})
    db.execute(update(CvParse).where(CvParse.document_id == d.id, CvParse.status == "draft")
               .values(status="superseded"))
    p = CvParse(user_id=user.id, document_id=d.id, parser_version=cv_parser.PARSER_VERSION,
                parsed_json=parsed, flags_json=flags)
    d.parsing_status = "parsed"
    db.add(p)
    audit(db, user.id, "document_parsed", "document", d.id, flags=len(flags))
    db.commit()
    return _parse_out(p)


@router.get("/documents/{doc_id}/parse")
def latest_parse(doc_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = _owned_doc(db, user, doc_id)
    p = db.scalar(select(CvParse).where(CvParse.document_id == d.id).order_by(CvParse.created_at.desc()))
    if p is None:
        raise HTTPException(404, "This document has not been parsed yet")
    return _parse_out(p)


@router.post("/documents/{doc_id}/parse/confirm")
def confirm_parse(doc_id: UUID, body: ConfirmCv, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The only path from parsed CV data into the trusted profile.

    The client submits the (possibly corrected) data. Every warning flag on the draft must be
    acknowledged by id, and every education entry must carry an explicit status (schema-enforced).
    Preferences are left untouched. The original document is never modified.
    """
    d = _owned_doc(db, user, doc_id)
    p = db.get(CvParse, body.parse_id)
    if p is None or p.user_id != user.id or p.document_id != d.id:
        raise HTTPException(404, "Parse draft not found")
    if p.status != "draft":
        raise HTTPException(409, f"This draft is {p.status}; run parse again")
    pending = [f["id"] for f in p.flags_json if f["severity"] == "warning" and f["id"] not in set(body.acknowledged_flags)]
    if pending:
        raise HTTPException(422, {"detail": "Acknowledge or fix all warnings before confirming", "unacknowledged": pending})
    if not body.profile.full_name.strip():
        raise HTTPException(422, "full_name is required")
    prof = get_profile(db, user)
    prof.full_name, prof.phone = body.profile.full_name, body.profile.phone
    prof.education_json = [{**e.model_dump(), "verified": True} for e in body.profile.education]
    prof.experience_json = [e.model_dump() for e in body.profile.experience]
    prof.projects_json = [x.model_dump() for x in body.profile.projects]
    prof.skills_json = [{**s.model_dump(), "verified": True} for s in body.profile.skills]
    prof.certifications_json = [c.model_dump() for c in body.profile.certifications]
    prof.profile_version += 1
    p.status, p.confirmed_at = "confirmed", utcnow()
    audit(db, user.id, "cv_confirmed_to_profile", "profile", prof.id, document_id=str(d.id), version=prof.profile_version)
    db.commit()
    return _out(prof)
