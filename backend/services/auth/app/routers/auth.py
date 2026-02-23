import logging
import secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from sqlalchemy.orm import Session

from backend.shared.rate_limiter.base import rate_limiter_factory

from .. import crud, schemas
from ..config import settings
from ..crud import (
    create_user_from_google,
    get_user_by_google_id,
    link_google_to_existing_user,
)
from ..database import get_db
from ..dependencies import create_tokens, get_current_user, validate_refresh_token
from ..google_oauth import get_google_user_info, refresh_google_access_token

logger = logging.getLogger(__name__)


def render_error_html(message: str, status_code: int = 400) -> HTMLResponse:
    """Возвращает HTML страницу с сообщением об ошибке и автоматическим редиректом на логин."""
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Authentication Error</title>
        <style>
            body {{ font-family: sans-serif; text-align: center; padding: 2rem; }}
            .error {{ color: #d32f2f; background: #ffebee; padding: 1rem; border-radius: 4px; }}
            .info {{ margin-top: 1rem; color: #666; }}
        </style>
        <script>
            // Автоматический редирект на страницу логина через 5 секунд
            setTimeout(() => {{
                window.location.href = '/login.html';
            }}, 5000);
        </script>
    </head>
    <body>
        <h2>Authentication Error</h2>
        <div class="error">{message}</div>
        <p class="info">You will be redirected to the login page in 5 seconds.</p>
        <p><a href="/login.html">Click here to go back now</a></p>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=status_code)


router = APIRouter(prefix="/auth", tags=["auth"])

# Rate limiting dependencies
register_rate_limit = rate_limiter_factory(
    endpoint="auth_register",
    max_requests=3,  # 3 запроса
    window_seconds=10,  # за 10 секунд
    identifier_type="ip",
)

login_rate_limit = rate_limiter_factory(
    endpoint="auth_login",
    max_requests=5,  # 5 запросов
    window_seconds=60,  # за минуту
    identifier_type="ip",
)

google_login_rate_limit = rate_limiter_factory(
    endpoint="auth_google_login",
    max_requests=10,  # 10 запросов
    window_seconds=60,  # за минуту
    identifier_type="ip",
)

refresh_rate_limit = rate_limiter_factory(
    endpoint="auth_refresh",
    max_requests=10,  # 10 запросов
    window_seconds=60,  # за минуту
    identifier_type="ip",
)


@router.post(
    "/register/",
    response_model=schemas.AuthResponse,
    dependencies=[Depends(register_rate_limit)],
)
def register(user: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = crud.get_user_by_email(db, user.email)
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    created_user = crud.create_user(db=db, user=user)
    tokens = create_tokens(created_user.id, created_user.email)
    crud.update_user_refresh_token(db, created_user, tokens["refresh_token"])
    return {
        "id": created_user.id,
        "email": created_user.email,
        "full_name": created_user.full_name,
        "picture_url": created_user.picture_url,
        "auth_provider": created_user.auth_provider,
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": tokens["token_type"],
    }


@router.post(
    "/token/",
    response_model=schemas.AuthResponse,
    dependencies=[Depends(login_rate_limit)],
)
def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
):
    user = crud.get_user_by_email(db, form_data.username)
    if not user or not crud.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    tokens = create_tokens(user.id, user.email)
    crud.update_user_refresh_token(db, user, tokens["refresh_token"])
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "picture_url": user.picture_url,
        "auth_provider": user.auth_provider,
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": tokens["token_type"],
    }


@router.post(
    "/refresh/",
    response_model=schemas.AuthResponse,
    dependencies=[Depends(refresh_rate_limit)],
)
def refresh_tokens(
    refresh_request: schemas.RefreshTokenRequest, db: Session = Depends(get_db)
):
    user_id = validate_refresh_token(refresh_request.refresh_token, db)
    user = crud.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    tokens = create_tokens(user.id, user.email)
    crud.update_user_refresh_token(db, user, tokens["refresh_token"])
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "picture_url": user.picture_url,
        "auth_provider": user.auth_provider,
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": tokens["token_type"],
    }


@router.get("/google/login", dependencies=[Depends(google_login_rate_limit)])
def google_login(request: Request):
    if not settings.google_client_id:
        raise HTTPException(status_code=500, detail="Google client id not configured")

    state = secrets.token_urlsafe(32)
    logger.info("Generated OAuth state for CSRF protection")

    scope = "openid email profile"
    authorization_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={settings.google_client_id}"
        f"&redirect_uri={settings.google_redirect_uri}"
        f"&response_type=code"
        f"&scope={scope.replace(' ', '%20')}"
        f"&access_type=offline"
        f"&prompt=consent"
        f"&state={state}"
    )

    response = JSONResponse({"login_url": authorization_url})
    response.set_cookie(
        key="oauth_state",
        value=state,
        max_age=600,
        httponly=True,
        secure=False,
        samesite="lax",
    )
    return response


@router.get("/callback/google", response_model=schemas.AuthResponse)
async def google_callback(request: Request, db: Session = Depends(get_db)):
    state_from_query = request.query_params.get("state")
    state_from_cookie = request.cookies.get("oauth_state")

    if not state_from_query or not state_from_cookie:
        logger.warning("CSRF state check failed: missing state")
        return render_error_html("Missing state parameter (CSRF check failed)")

    if state_from_query != state_from_cookie:
        logger.warning(
            f"CSRF state mismatch: query_state={state_from_query[:10]}..., "
            f"cookie_state={state_from_cookie[:10] if state_from_cookie else 'None'}..."
        )
        return render_error_html("Invalid state parameter (CSRF check failed)")

    code = request.query_params.get("code")
    error = request.query_params.get("error")

    if error:
        error_description = request.query_params.get(
            "error_description", "Unknown error"
        )
        logger.warning(f"Google OAuth error: {error} - {error_description}")
        return render_error_html(f"Google OAuth error: {error}")

    if not code:
        return render_error_html("Missing authorization code")

    if not settings.google_client_id or not settings.google_client_secret:
        logger.error("Google OAuth credentials not configured")
        return render_error_html("Google OAuth not configured", status_code=500)

    token_url = "https://oauth2.googleapis.com/token"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                token_url,
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": settings.google_redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
    except Exception as e:
        logger.error(f"Failed to connect to Google token endpoint: {str(e)}")
        return render_error_html("Failed to connect to Google", status_code=500)

    if resp.status_code != 200:
        logger.error(f"Google token response error: {resp.status_code} - {resp.text}")
        return render_error_html("Failed to fetch tokens from Google")

    tokens = resp.json()
    id_token_str = tokens.get("id_token")
    if not id_token_str:
        logger.error("No id_token returned by Google")
        return render_error_html("No id_token returned by Google")

    try:
        id_info = id_token.verify_oauth2_token(
            id_token_str, google_requests.Request(), settings.google_client_id
        )
    except ValueError as e:
        logger.error(f"Invalid Google id_token: {str(e)}")
        return render_error_html(f"Invalid Google id_token: {str(e)}")

    google_sub = id_info.get("sub")
    email = id_info.get("email")
    name = id_info.get("name")
    picture = id_info.get("picture")

    if not google_sub or not email:
        logger.warning("Incomplete token info from Google")
        return render_error_html("Incomplete token info from Google")

    logger.info(f"Verified Google user: {email}")

    user = get_user_by_google_id(db, google_sub)
    if not user:
        user_by_email = crud.get_user_by_email(db, email)
        if user_by_email:
            logger.info(f"Linking Google account to existing user: {email}")
            user = link_google_to_existing_user(
                db, user_by_email, google_sub, tokens.get("refresh_token")
            )
        else:
            logger.info(f"Creating new user from Google: {email}")
            user = create_user_from_google(
                db,
                email=email,
                google_id=google_sub,
                full_name=name,
                picture_url=picture,
                refresh_token=tokens.get("refresh_token"),
            )

    our_tokens = create_tokens(user.id, user.email)
    crud.update_user_refresh_token(db, user, our_tokens["refresh_token"])

    logger.info(f"User authenticated via Google: user_id={user.id}")

    # Генерируем HTML страницу, которая сохранит токены в localStorage и перенаправит на главную
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Authentication Successful</title>
        <script>
            // Сохраняем токены в localStorage
            localStorage.setItem('access_token', '{our_tokens["access_token"]}');
            localStorage.setItem('refresh_token', '{our_tokens["refresh_token"]}');
            localStorage.setItem('user_info', JSON.stringify({{
                id: {user.id},
                email: '{user.email}',
                full_name: '{user.full_name or ""}',
                picture_url: '{user.picture_url or ""}',
                auth_provider: '{user.auth_provider}'
            }}));
            // Перенаправляем на главную страницу
            window.location.href = '/';
        </script>
    </head>
    <body>
        <p>Authentication successful. Redirecting...</p>
    </body>
    </html>
    """

    response = HTMLResponse(content=html_content)
    response.delete_cookie("oauth_state")
    return response


@router.post("/google/refresh-info", response_model=schemas.UserOut)
async def refresh_google_user_info(
    user_id: int = Depends(get_current_user), db: Session = Depends(get_db)
):
    tokens = await refresh_google_access_token(db, user_id)
    if not tokens:
        raise HTTPException(
            status_code=400,
            detail="Failed to refresh Google access token",
        )

    access_token = tokens.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=400,
            detail="No access token in Google response",
        )

    user_info = await get_google_user_info(access_token)
    if not user_info:
        raise HTTPException(
            status_code=400,
            detail="Failed to fetch user info from Google",
        )

    user = crud.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    user.full_name = user_info.get("name", user.full_name)
    user.picture_url = user_info.get("picture", user.picture_url)
    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "picture_url": user.picture_url,
        "auth_provider": user.auth_provider,
    }
