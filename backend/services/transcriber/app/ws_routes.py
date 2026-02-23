import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.shared.rate_limiter.websocket import get_websocket_rate_limiter

from .dependencies import verify_websocket_token
from .session_manager import SessionManager

router = APIRouter()
logger = logging.getLogger("WSRoutes")
session_manager = SessionManager()
ws_rate_limiter = get_websocket_rate_limiter()


@router.websocket("/ws/stream")
async def websocket_endpoint(websocket: WebSocket):
    # Получаем IP адрес клиента
    client_ip = websocket.client.host if websocket.client else "unknown"

    # Верифицируем токен перед подключением
    try:
        payload = await verify_websocket_token(websocket)
        user_id = payload.get("sub")
        email = payload.get("email")
        if not user_id:
            logger.warning("Token missing 'sub' claim")
            await websocket.close(code=1008)
            return
        logger.debug(f"WebSocket connection authorized for user {user_id} ({email})")
    except Exception as e:
        logger.warning(f"WebSocket authentication failed: {e}")
        await websocket.close(code=1008)
        return

    # Проверяем rate limiting для подключения
    allowed, error_message = await ws_rate_limiter.check_connection(
        ip=client_ip, user_id=int(user_id) if user_id else None
    )

    if not allowed:
        logger.warning(
            f"WebSocket connection blocked by rate limiter: "
            f"IP={client_ip}, user_id={user_id}, reason={error_message}"
        )
        await websocket.close(code=1008, reason=error_message)
        return

    # Регистрируем подключение
    connection_id = str(id(websocket))
    registration_success = await ws_rate_limiter.register_connection(
        ip=client_ip,
        user_id=int(user_id) if user_id else None,
        connection_id=connection_id,
    )

    if not registration_success:
        logger.error(
            f"Failed to register WebSocket connection: IP={client_ip}, user_id={user_id}"
        )
        await websocket.close(code=1011, reason="Internal server error")
        return

    await websocket.accept()
    session = session_manager.create(websocket, user_id=user_id)
    logger.debug(f"WebSocket connection established: IP={client_ip}, user_id={user_id}")

    try:
        while True:
            # Получаем сообщение
            try:
                message = await websocket.receive()
            except WebSocketDisconnect:
                # Клиент отключился, выходим из цикла
                break
            except RuntimeError as e:
                # Другие ошибки runtime, например, соединение уже закрыто
                logger.debug(f"WebSocket receive error: {e}")
                break

            if "text" in message:
                # Проверяем rate limiting для текстовых сообщений
                allowed, error_message = await ws_rate_limiter.check_message(
                    ip=client_ip, user_id=int(user_id) if user_id else None
                )

                if not allowed:
                    logger.warning(
                        f"WebSocket message blocked by rate limiter: "
                        f"IP={client_ip}, user_id={user_id}, reason={error_message}"
                    )
                    await websocket.send_json(
                        {"type": "error", "message": error_message}
                    )
                    continue

                try:
                    data = json.loads(message["text"])
                    msg_type = data.get("type")

                    if msg_type == "start":
                        language = data.get("language", "RU")
                        await session_manager.start_worker(
                            session, mode="transcription", language=language
                        )
                        await websocket.send_json(
                            {"type": "status", "message": "Transcription started"}
                        )

                    elif msg_type == "start_translation":
                        source = data.get("source_lang", "EN")
                        target = data.get("target_lang", "RU")
                        await session_manager.start_worker(
                            session,
                            mode="translation",
                            source_lang=source,
                            target_lang=target,
                        )
                        await websocket.send_json(
                            {"type": "status", "message": "Translation started"}
                        )

                    elif msg_type == "stop":
                        await session_manager.stop_session(session)
                        # После остановки сессии можно выйти из цикла, т.к. клиент ожидает закрытия соединения
                        # Но оставляем соединение открытым для получения сообщения done
                        continue

                except json.JSONDecodeError:
                    logger.error("Invalid JSON received")

            elif "bytes" in message:
                # Для аудио сообщений также проверяем rate limiting
                allowed, error_message = await ws_rate_limiter.check_message(
                    ip=client_ip, user_id=int(user_id) if user_id else None
                )

                if not allowed:
                    logger.warning(
                        f"WebSocket audio message blocked by rate limiter: "
                        f"IP={client_ip}, user_id={user_id}, reason={error_message}"
                    )
                    # Для аудио сообщений не отправляем ответ, просто пропускаем
                    continue

                await session_manager.handle_audio_chunk(session, message["bytes"])

    except WebSocketDisconnect:
        # Минимальное логирование: убрали info об отключении
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        # Гарантируем остановку сессии и очистку ресурсов, если ещё не остановлена
        if not session.stopped:
            await session_manager.stop_session(session)
        session_manager.remove(websocket)

        # Удаляем регистрацию подключения из rate limiter
        await ws_rate_limiter.unregister_connection(
            ip=client_ip,
            user_id=int(user_id) if user_id else None,
            connection_id=connection_id,
        )
        logger.debug(
            f"WebSocket connection unregistered: IP={client_ip}, user_id={user_id}"
        )
