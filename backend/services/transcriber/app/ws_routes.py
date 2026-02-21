import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .dependencies import verify_websocket_token
from .session_manager import SessionManager

router = APIRouter()
logger = logging.getLogger("WSRoutes")
session_manager = SessionManager()


@router.websocket("/ws/stream")
async def websocket_endpoint(websocket: WebSocket):
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

    await websocket.accept()
    session = session_manager.create(websocket, user_id=user_id)
    # Минимальное логирование: убрали info о подключении

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
