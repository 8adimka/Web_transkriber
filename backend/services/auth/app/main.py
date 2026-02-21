from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers.auth import router

app = FastAPI(title="Auth Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://localhost:8001",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(router, tags=["auth"])


@app.get("/health")
def health():
    return {"status": "ok"}
