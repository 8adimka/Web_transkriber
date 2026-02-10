import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

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

RECORDS_DIR = "records"


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/download/{filename}")
async def download_file(filename: str):
    file_path = os.path.join(RECORDS_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="text/plain", filename=filename)
    return {"error": "File not found"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
