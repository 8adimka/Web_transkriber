import logging

import httpx
from sqlalchemy.orm import Session

from . import crud
from .config import settings

logger = logging.getLogger(__name__)


async def refresh_google_access_token(db: Session, user_id: int) -> dict | None:
    user = crud.get_user_by_id(db, user_id)
    if not user:
        logger.error(f"User not found: {user_id}")
        return None

    google_refresh_token = crud.get_google_refresh_token(db, user)
    if not google_refresh_token:
        logger.warning(f"No Google refresh token for user: {user_id}")
        return None

    if not settings.google_client_id or not settings.google_client_secret:
        logger.error("Google OAuth credentials not configured")
        return None

    token_url = "https://oauth2.googleapis.com/token"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                token_url,
                data={
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "refresh_token": google_refresh_token,
                    "grant_type": "refresh_token",
                },
                headers={"Accept": "application/json"},
            )
    except Exception as e:
        logger.error(f"Failed to refresh Google token: {str(e)}")
        return None

    if resp.status_code != 200:
        logger.error(f"Google token refresh error: {resp.status_code} - {resp.text}")
        return None

    tokens = resp.json()
    return tokens


async def get_google_user_info(access_token: str) -> dict | None:
    userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
    except Exception as e:
        logger.error(f"Failed to fetch Google user info: {str(e)}")
        return None

    if resp.status_code != 200:
        logger.error(f"Google userinfo error: {resp.status_code} - {resp.text}")
        return None

    return resp.json()
