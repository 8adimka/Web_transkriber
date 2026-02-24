from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.shared.rate_limiter.metrics import router as rate_limiter_router
from backend.shared.token_tracker.sync_worker import (
    start_token_sync_worker,
    stop_token_sync_worker,
)

from .routers.auth import router as auth_router
from .routers.token_stats import router as token_stats_router
from .routers.user_profile import router as user_profile_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Запускаем воркер синхронизации токенов при старте
    try:
        await start_token_sync_worker()
        print("Token sync worker started")
    except Exception as e:
        print(f"Failed to start token sync worker: {e}")
    yield
    # Останавливаем воркер при остановке
    try:
        await stop_token_sync_worker()
        print("Token sync worker stopped")
    except Exception as e:
        print(f"Failed to stop token sync worker: {e}")


app = FastAPI(title="Auth Service", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://localhost:8001",
        "http://localhost:3000",
        "http://localhost",
        "https://localhost",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(auth_router, tags=["auth"])
app.include_router(rate_limiter_router, tags=["rate-limiter"])
app.include_router(token_stats_router)
app.include_router(user_profile_router)


@app.get("/health")
def health():
    return {"status": "ok"}
