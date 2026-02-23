import os

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend.shared.rate_limiter.metrics import router as rate_limiter_router

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

# Подключение роутов
app.include_router(ws_router)
app.include_router(rate_limiter_router, tags=["rate-limiter"])

RECORDS_DIR = "records"


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/download/{filename}")
async def download_file(
    filename: str,
    token: str = Query(..., description="JWT access token"),
):
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

    file_path = os.path.join(RECORDS_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="text/plain", filename=filename)
    return {"error": "File not found"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
