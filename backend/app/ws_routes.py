import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .session_manager import SessionManager

router = APIRouter()
logger = logging.getLogger("WSRoutes")
session_manager = SessionManager()


@router.websocket("/ws/stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session = session_manager.create(websocket)
    logger.info(f"WebSocket connected: {id(websocket)}")

    try:
        while True:
            # Получаем сообщение
            message = await websocket.receive()

            if "text" in message:
                try:
                    data = json.loads(message["text"])
                    msg_type = data.get("type")

                    if msg_type == "start":
                        language = data.get("language", "RU")
                        await session_manager.start_transcription_worker(
                            session, language
                        )
                        await websocket.send_json(
                            {"type": "status", "message": "Transcription started"}
                        )

                    elif msg_type == "start_translation":
                        source = data.get("source_lang", "EN")
                        target = data.get("target_lang", "RU")
                        await session_manager.start_translation_worker(
                            session, source, target
                        )
                        await websocket.send_json(
                            {"type": "status", "message": "Translation started"}
                        )

                    elif msg_type == "stop":
                        await session_manager.stop_session(session)

                except json.JSONDecodeError:
                    logger.error("Invalid JSON received")

            elif "bytes" in message:
                await session_manager.handle_audio_chunk(session, message["bytes"])

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {id(websocket)}")
        await session_manager.stop_session(session)
        session_manager.remove(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await session_manager.stop_session(session)
            session_manager.remove(websocket)
        except:
            pass
