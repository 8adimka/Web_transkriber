from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.shared.rate_limiter.metrics import router as rate_limiter_router

from .routers.auth import router as auth_router

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

app.include_router(auth_router, tags=["auth"])
app.include_router(rate_limiter_router, tags=["rate-limiter"])


@app.get("/health")
def health():
    return {"status": "ok"}
