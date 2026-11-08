from datetime import datetime
from typing import List, Optional

from sqlalchemy import delete, desc, func, select
from sqlalchemy.orm import Session

from .database import Transcription


def create_transcription(
    db: Session,
    user_id: int,
    filename: str,
    content: str,
    orig_language: str = "RU",
    translate_to: Optional[str] = None,
    file_size: Optional[int] = None,
) -> Transcription:
    """Создание новой транскрипции в БД"""
    db_transcription = Transcription(
        user_id=user_id,
        filename=filename,
        content=content,
        orig_language=orig_language,
        translate_to=translate_to,
        file_size=file_size,
        created_at=datetime.utcnow(),
    )
    db.add(db_transcription)
    db.commit()
    db.refresh(db_transcription)
    return db_transcription


def get_transcription_by_id_and_user(
    db: Session, transcription_id: int, user_id: int
) -> Optional[Transcription]:
    """Получение транскрипции по ID с проверкой владельца"""
    result = db.execute(
        select(Transcription).where(
            Transcription.id == transcription_id, Transcription.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


def get_user_transcriptions(
    db: Session,
    user_id: int,
    skip: int = 0,
    limit: int = 100,
    preview_chars: Optional[int] = None,
) -> List:
    """Получение списка транскрипций пользователя с пагинацией"""
    if preview_chars is None:
        statement = select(Transcription)
    else:
        # Do not materialize entire books merely to display a library preview.
        statement = select(
            Transcription.id, Transcription.user_id, Transcription.filename,
            func.substr(Transcription.content, 1, preview_chars).label("content"),
            Transcription.orig_language, Transcription.translate_to,
            Transcription.file_size, Transcription.created_at,
        )
    result = db.execute(statement.where(Transcription.user_id == user_id)
                        .order_by(desc(Transcription.created_at)).offset(skip).limit(limit))
    return list(result.scalars().all()) if preview_chars is None else list(result.all())



def delete_transcription(db: Session, transcription_id: int, user_id: int) -> bool:
    """Удаление транскрипции с проверкой владельца"""
    result = db.execute(
        delete(Transcription).where(
            Transcription.id == transcription_id, Transcription.user_id == user_id
        )
    )
    db.commit()
    return result.rowcount > 0


def count_user_transcriptions(db: Session, user_id: int) -> int:
    """Подсчет количества транскрипций пользователя"""
    return db.scalar(select(func.count()).select_from(Transcription).where(Transcription.user_id == user_id)) or 0
