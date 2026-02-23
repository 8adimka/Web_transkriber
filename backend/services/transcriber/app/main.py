import os

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from backend.shared.rate_limiter.metrics import router as rate_limiter_router

from . import crud, schemas
from .database import get_db, init_db
from .dependencies import verify_token
from .ws_routes import router as ws_router

app = FastAPI(title="Web Transcriber API")

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Инициализация БД при старте
@app.on_event("startup")
def startup_event():
    init_db()


# Подключение роутов
app.include_router(ws_router)
app.include_router(rate_limiter_router, tags=["rate-limiter"])


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/transcriptions", response_model=schemas.TranscriptionList)
def get_transcriptions(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    token: str = Query(..., description="JWT access token"),
    db: Session = Depends(get_db),
):
    """Получение списка транскрипций пользователя"""
    try:
        payload = verify_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing user id",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
        )

    # Получаем транскрипции пользователя
    transcriptions = crud.get_user_transcriptions(
        db, user_id=int(user_id), skip=skip, limit=limit
    )
    total = crud.count_user_transcriptions(db, user_id=int(user_id))

    # Конвертируем SQLAlchemy объекты в Pydantic модели
    transcription_models = []
    for transcription in transcriptions:
        # Получаем значения полей
        translate_to_value = transcription.translate_to
        # Проверяем, что значение не None и не пустая строка
        translate_to = None
        if translate_to_value is not None and str(translate_to_value) != "":
            translate_to = str(translate_to_value)

        # Создаем словарь с данными
        data = {
            "id": transcription.id,
            "user_id": transcription.user_id,
            "filename": transcription.filename,
            "content": transcription.content,
            "orig_language": transcription.orig_language or "RU",
            "translate_to": translate_to,
            "file_size": transcription.file_size,
            "created_at": transcription.created_at,
        }
        transcription_models.append(schemas.Transcription(**data))

    return schemas.TranscriptionList(
        transcriptions=transcription_models,
        total=total,
        skip=skip,
        limit=limit,
    )


@app.get("/transcriptions/{transcription_id}/download")
def download_transcription(
    transcription_id: int,
    token: str = Query(..., description="JWT access token"),
    db: Session = Depends(get_db),
):
    """Скачивание транскрипции по ID"""
    try:
        payload = verify_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing user id",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
        )

    # Получаем транскрипцию с проверкой владельца
    transcription = crud.get_transcription_by_id_and_user(
        db, transcription_id=transcription_id, user_id=int(user_id)
    )
    if not transcription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcription not found or access denied",
        )

    # Генерируем файл на лету
    return Response(
        content=transcription.content,
        media_type="text/plain",
        headers={
            "Content-Disposition": f"attachment; filename={transcription.filename}"
        },
    )


@app.delete(
    "/transcriptions/{transcription_id}",
    response_model=schemas.TranscriptionDeleteResponse,
)
def delete_transcription(
    transcription_id: int,
    token: str = Query(..., description="JWT access token"),
    db: Session = Depends(get_db),
):
    """Удаление транскрипции по ID"""
    try:
        payload = verify_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing user id",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
        )

    # Удаляем транскрипцию с проверкой владельца
    success = crud.delete_transcription(
        db, transcription_id=transcription_id, user_id=int(user_id)
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcription not found or access denied",
        )

    return schemas.TranscriptionDeleteResponse(
        success=True,
        message=f"Transcription {transcription_id} deleted successfully",
    )


# Старый endpoint для обратной совместимости (можно удалить после обновления фронтенда)
@app.get("/download/{filename}")
async def download_file(
    filename: str,
    token: str = Query(..., description="JWT access token"),
):
    """Старый endpoint для скачивания файлов (обратная совместимость)"""
    # Верифицируем токен
    try:
        payload = verify_token(token)
        user_id = payload.get("sub")
        # Можно добавить дополнительную проверку, что файл принадлежит пользователю
        # но пока просто проверяем валидность токена
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
        )

    file_path = os.path.join("records", filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="text/plain", filename=filename)
    return {"error": "File not found"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
