import os
from pathlib import Path

import jwt
from fastapi import HTTPException, WebSocket, status


def get_public_key() -> str:
    """Читает публичный ключ из файла."""
    key_path = Path("/app/keys/public.pem")
    if not key_path.exists():
        # Для разработки: если файла нет, используем ключ из переменной окружения
        public_key_env = os.getenv("AUTH_PUBLIC_KEY")
        if public_key_env:
            return public_key_env
        raise RuntimeError("Public key not found")
    return key_path.read_text()


def verify_token(token: str) -> dict:
    """Верифицирует JWT токен и возвращает payload."""
    public_key = get_public_key()
    try:
        payload = jwt.decode(
            token, public_key, algorithms=["RS256"], options={"verify_exp": True}
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
        )
    except jwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {str(e)}"
        )


async def verify_websocket_token(websocket: WebSocket) -> dict:
    """Извлекает токен из query параметров WebSocket и верифицирует его."""
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing"
        )
    return verify_token(token)
