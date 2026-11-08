"""Authenticated Reader library, UTF-16 reading anchors and explicit translation.

Document extraction is local. Only a user-selected word/phrase reaches DeepL.
"""

import asyncio
from datetime import datetime, timezone
import os
from time import time
from typing import Optional
from urllib.parse import unquote
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, conint, constr, validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from backend.shared.rate_limiter.base import get_rate_limiter
from backend.shared.token_tracker import get_token_tracker

from . import crud
from .database import ReaderState, Transcription, get_db
from .dependencies import verify_token
from .document_import import DocumentImportError, extract_document

router = APIRouter(prefix="/reader", tags=["reader"])
bearer = HTTPBearer(auto_error=False)
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 5_000_000
LANGUAGE = constr(strict=True, regex=r"^[A-Za-z]{2}(?:-[A-Za-z]{2,4})?$")


def problem(status_code: int, code: str, message: str, headers=None):
    return HTTPException(status_code=status_code, detail={"code": code, "message": message}, headers=headers)


def reader_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer)) -> int:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise problem(401, "authentication_required", "Please sign in to use Reader.", {"WWW-Authenticate": "Bearer"})
    try:
        payload = verify_token(credentials.credentials)
        value = payload.get("sub")
        if not isinstance(value, (str, int)) or isinstance(value, bool) or not str(value).isdigit():
            raise ValueError("Invalid owner")
        user_id = int(value)
        if user_id <= 0:
            raise ValueError("Invalid owner")
        return user_id
    except (HTTPException, ValueError, TypeError):
        raise problem(401, "authentication_required", "Please sign in again.", {"WWW-Authenticate": "Bearer"})


class Languages(BaseModel):
    source_lang: LANGUAGE = "EN"
    target_lang: LANGUAGE = "RU"

    @validator("source_lang", "target_lang")
    def normalize_language(cls, value):
        return value.upper()


class CreateDocument(Languages):
    title: constr(strict=True, min_length=1, max_length=255)
    content: constr(strict=True, min_length=1, max_length=MAX_TEXT_CHARS)
    client_id: UUID

    @validator("title", "content")
    def readable_text(cls, value):
        if not value.strip() or "\x00" in value or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ValueError("Text must be non-empty Unicode without null characters")
        return value


class ReadingProgress(BaseModel):
    position: conint(strict=True, ge=0, le=20_000_000)
    page: conint(strict=True, ge=1, le=20_000_000)
    updated_at_ms: Optional[conint(strict=True, ge=0, le=9_007_199_254_740_991)] = None


class TranslateSelection(Languages):
    text: constr(strict=True, min_length=1, max_length=5000)

    @validator("text")
    def meaningful_selection(cls, value):
        if not value.strip() or "\x00" in value or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ValueError("Select non-empty Unicode text")
        return value.strip()


def _document_response(document, state=None):
    return {
        "id": document.id,
        "title": document.filename,
        "content": document.content,
        "source_lang": document.orig_language or "EN",
        "target_lang": document.translate_to or "RU",
        "position": state.position if state else 0,
        "page": state.page if state else 1,
        "progress_updated_at_ms": state.position_updated_at_ms if state else 0,
        "created_at": document.created_at,
    }


def _owned_document(db: Session, document_id: int, user_id: int):
    document = crud.get_transcription_by_id_and_user(db, document_id, user_id)
    if document is None:
        raise problem(404, "document_not_found", "The text was not found.")
    return document


def _existing_creation(db, user_id, client_id):
    result = db.execute(
        select(Transcription, ReaderState).join(ReaderState, ReaderState.transcription_id == Transcription.id)
        .where(ReaderState.user_id == user_id, ReaderState.client_id == str(client_id), Transcription.user_id == user_id)
    ).first()
    return result


def _same_creation(existing, data):
    document, state = existing
    if (document.content != data.content or document.filename != data.title or
            document.orig_language != data.source_lang or document.translate_to != data.target_lang):
        raise problem(409, "idempotency_conflict", "This save key was already used for different text.")
    return _document_response(document, state)


def _create_document(db: Session, user_id: int, data: CreateDocument):
    existing = _existing_creation(db, user_id, data.client_id)
    if existing:
        return _same_creation(existing, data)
    document = Transcription(
        user_id=user_id, filename=data.title, content=data.content,
        orig_language=data.source_lang, translate_to=data.target_lang,
        file_size=len(data.content.encode("utf-8")), created_at=datetime.now(timezone.utc),
    )
    try:
        db.add(document)
        db.flush()
        state = ReaderState(transcription_id=document.id, user_id=user_id, client_id=str(data.client_id))
        db.add(state)
        db.commit()
        db.refresh(document)
        db.refresh(state)
        return _document_response(document, state)
    except IntegrityError:
        db.rollback()
        # A concurrent retry may win the unique key after this request began.
        existing = _existing_creation(db, user_id, data.client_id)
        if existing:
            return _same_creation(existing, data)
        raise problem(503, "save_failed", "The text could not be saved. Please retry.")
    except SQLAlchemyError:
        db.rollback()
        raise problem(503, "save_failed", "The text could not be saved. Please retry.")


@router.post("/documents")
def create_document(data: CreateDocument, user_id: int = Depends(reader_user), db: Session = Depends(get_db)):
    return _create_document(db, user_id, data)


@router.post("/import")
async def import_document(
    request: Request,
    filename: str = Header(..., alias="X-File-Name", max_length=2048),
    client_id: UUID = Header(..., alias="Idempotency-Key"),
    source_lang: LANGUAGE = Query("EN"),
    target_lang: LANGUAGE = Query("RU"),
    user_id: int = Depends(reader_user),
    db: Session = Depends(get_db),
):
    size = 0
    chunks = []
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise problem(413, "too_large", "The document must be smaller than 10 MiB.")
        chunks.append(chunk)
    if not size:
        raise problem(422, "invalid_document", "The document is empty.")
    try:
        decoded_filename = unquote(filename, errors="strict")
        imported = await run_in_threadpool(extract_document, b"".join(chunks), decoded_filename)
        data = CreateDocument(
            title=imported["title"], content=imported["content"], client_id=client_id,
            source_lang=source_lang, target_lang=target_lang,
        )
    except DocumentImportError as error:
        code = error.code
        status_code = 413 if code in ("too_large", "file_too_large", "text_too_large") else 415 if code == "unsupported_format" else 422
        raise problem(status_code, code, error.message)
    except (UnicodeError, ValueError, KeyError, TypeError):
        raise problem(422, "invalid_document", "The document could not be read.")
    return await run_in_threadpool(_create_document, db, user_id, data)


@router.get("/documents/{document_id}")
def read_document(
    document_id: int = Path(..., ge=1), user_id: int = Depends(reader_user), db: Session = Depends(get_db)
):
    document = _owned_document(db, document_id, user_id)
    state = db.get(ReaderState, document_id)
    return _document_response(document, state)


@router.patch("/documents/{document_id}/progress")
def save_progress(
    data: ReadingProgress, document_id: int = Path(..., ge=1),
    user_id: int = Depends(reader_user), db: Session = Depends(get_db),
):
    document = _owned_document(db, document_id, user_id)
    # Browser String.length/slice use UTF-16 code units, not Python code points.
    text_length = len(document.content.encode("utf-16-le")) // 2
    if data.position > text_length:
        raise problem(422, "invalid_position", "Reading position exceeds the text length.")
    stamp = data.updated_at_ms if data.updated_at_ms is not None else int(time() * 1000)
    for attempt in range(2):
        state = db.get(ReaderState, document_id)
        if state is None:
            # A concurrent initial PATCH can race this insert; retry atomically.
            db.add(ReaderState(
                transcription_id=document_id, user_id=user_id,
                position=data.position, page=data.page,
                position_updated_at_ms=stamp, updated_at=datetime.now(timezone.utc),
            ))
        else:
            # This WHERE is evaluated by the database after acquiring the row
            # lock. A delayed earlier request cannot undo the latest anchor.
            db.execute(update(ReaderState).where(
                ReaderState.transcription_id == document_id,
                ReaderState.user_id == user_id,
                ReaderState.position_updated_at_ms <= stamp,
            ).values(
                position=data.position, page=data.page,
                position_updated_at_ms=stamp, updated_at=datetime.now(timezone.utc),
            ))
        try:
            db.commit()
            db.expire_all()
            state = db.get(ReaderState, document_id)
            return {
                "id": document_id, "position": state.position, "page": state.page,
                "updated_at": state.updated_at, "updated_at_ms": state.position_updated_at_ms,
                "progress_updated_at_ms": state.position_updated_at_ms,
            }
        except IntegrityError:
            db.rollback()
            if attempt:
                raise problem(503, "progress_failed", "Reading progress could not be saved.")
        except SQLAlchemyError:
            db.rollback()
            raise problem(503, "progress_failed", "Reading progress could not be saved.")



@router.post("/translate")
async def translate_selection(data: TranslateSelection, user_id: int = Depends(reader_user)):
    if data.source_lang == data.target_lang:
        return {"translated": data.text, "source_lang": data.source_lang, "target_lang": data.target_lang}
    api_key = os.getenv("DEEPL_API_KEY", "").strip()
    if not api_key:
        raise problem(503, "translation_unavailable", "Translation is not configured.")
    limiter = get_rate_limiter()
    if await limiter.is_limited(str(user_id), "reader_translate", 60, 60, identifier_type="user"):
        raise problem(429, "translation_limit", "Please wait before translating more text.", {"Retry-After": "5"})
    endpoint = "https://api-free.deepl.com/v2/translate" if api_key.endswith(":fx") else "https://api.deepl.com/v2/translate"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=3.0)) as client:
            response = await client.post(
                endpoint, headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
                json={"text": [data.text], "source_lang": data.source_lang, "target_lang": data.target_lang},
            )
        # DeepL documents 429/529 as throttling and 456 as quota exhaustion.
        # https://developers.deepl.com/docs/best-practices/error-handling
        if response.status_code in (429, 456, 529):
            raise problem(429, "translation_limit", "Translation limit reached. Please try later.", {"Retry-After": "60"})
        if response.status_code in (401, 403):
            raise problem(503, "translation_unavailable", "Translation is temporarily unavailable.")
        if response.status_code != 200:
            raise problem(502, "translation_failed", "The translation service could not process the selection.")
        result = response.json()
        translated = result["translations"][0]["text"]
        if not isinstance(translated, str) or not translated.strip():
            raise ValueError("Empty translation")
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        raise problem(502, "translation_failed", "The translation service did not return a result.")
    try:
        await asyncio.wait_for(get_token_tracker().track_deepl_usage(
            user_id=user_id, text=data.text,
            metadata={"source_lang": data.source_lang, "target_lang": data.target_lang, "mode": "reader"},
        ), timeout=1.0)
    except Exception:
        # Accounting outages must not discard a translation already received.
        pass
    return {"translated": translated, "source_lang": data.source_lang, "target_lang": data.target_lang}
