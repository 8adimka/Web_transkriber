import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .session_manager import SessionManager
from .utils import logger

router = APIRouter()
sessions = SessionManager()


@router.websocket("/ws/stream")
async def ws_stream(websocket: WebSocket):
    await websocket.accept()
    session = sessions.create(websocket)
    logger.info(f"New connection: {websocket.client}")

    try:
        while True:
            # Получаем сообщение (текст или бинарные данные)
            message = await websocket.receive()

            if "text" in message:
                # Управляющие команды JSON
                try:
                    data = json.loads(message["text"])
                    msg_type = data.get("type")

                    if msg_type == "start":
                        logger.info("Command START received (transcription mode)")
                        language = data.get("language", "RU")
                        await sessions.start_transcription_worker(session, language)

                    elif msg_type == "start_translation":
                        logger.info("Command START_TRANSLATION received")
                        source_lang = data.get("source_lang", "EN")
                        target_lang = data.get("target_lang", "RU")
                        await sessions.start_translation_worker(
                            session, source_lang, target_lang
                        )

                    elif msg_type == "stop":
                        logger.info("Command STOP received")
                        await sessions.stop_session(session)
                        break  # Выход из цикла для закрытия сокета

                except json.JSONDecodeError:
                    logger.warning("Invalid JSON received")

            elif "bytes" in message:
                # Аудио данные
                logger.info(f"Received binary data, size: {len(message['bytes'])}")
                if session.active and session.processor:
                    await sessions.handle_audio_chunk(session, message["bytes"])

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if session.active:
            await sessions.stop_session(session)
        sessions.remove(websocket)
