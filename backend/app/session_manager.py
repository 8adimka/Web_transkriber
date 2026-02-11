import asyncio
import os
from typing import Optional

import aiofiles
from fastapi import WebSocket

from .dialogue_processor import DialogueProcessor
from .utils import get_timestamp_filename, logger

QUEUE_MAX_SIZE = int(os.getenv("QUEUE_MAX_SIZE", 50))
RECORDS_DIR = "records"


class Session:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.transcript_log = []
        self.speaker_log = []  # Для хранения спикера каждой реплики
        self.filename = get_timestamp_filename()
        self.processor: Optional[DialogueProcessor] = None
        self.processor_task: Optional[asyncio.Task] = None
        self.active = True

    def append_transcript(self, text: str, speaker: str = ""):
        logger.info(f"Appending transcript: speaker={speaker}, text={text[:50]}...")
        self.transcript_log.append(text)
        self.speaker_log.append(speaker)

    async def save_file(self) -> str:
        logger.info(
            f"Saving file {self.filename} with {len(self.transcript_log)} transcripts"
        )
        # Убедимся, что директория существует
        os.makedirs(RECORDS_DIR, exist_ok=True)
        filepath = os.path.join(RECORDS_DIR, self.filename)
        try:
            async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
                await f.write("ТРАНСКРИПЦИЯ ДИАЛОГА\n")
                await f.write(
                    f"Создано: {self.filename.replace('dialog_', '').replace('.txt', '').replace('_', ' ')}\n"
                )
                await f.write("=" * 60 + "\n\n")

                if self.transcript_log:
                    for i, (text, speaker) in enumerate(
                        zip(self.transcript_log, self.speaker_log)
                    ):
                        speaker_name = (
                            "Я"
                            if speaker == "me"
                            else "Собеседник"
                            if speaker
                            else "Неизвестно"
                        )
                        await f.write(f"{speaker_name}: {text}\n\n")
                else:
                    await f.write("Нет транскрибированных данных.\n")

            logger.info(f"File saved successfully: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Error saving file {filepath}: {e}", exc_info=True)
            raise


class SessionManager:
    def __init__(self):
        self.active_sessions = {}

    def create(self, websocket: WebSocket) -> Session:
        session = Session(websocket)
        self.active_sessions[id(websocket)] = session
        return session

    def remove(self, websocket: WebSocket):
        if id(websocket) in self.active_sessions:
            del self.active_sessions[id(websocket)]

    async def start_worker(self, session: Session):
        logger.info("Creating DialogueProcessor")
        session.processor = DialogueProcessor(
            session.websocket, session.append_transcript
        )
        logger.info("Starting DialogueProcessor")
        session.processor_task = asyncio.create_task(session.processor.start())
        logger.info("DialogueProcessor started")

    async def stop_session(self, session: Session):
        """Останавливает сессию немедленно, возвращая уже транскрибированные данные"""
        logger.info("Stopping session immediately")
        session.active = False

        # Останавливаем процессор немедленно
        try:
            if session.processor:
                logger.info("Stopping processor immediately...")
                await session.processor.stop()
                logger.info("Processor stopped immediately")
            else:
                logger.warning("No processor to stop")
        except Exception as e:
            logger.error(f"Error stopping processor: {e}", exc_info=True)

        # Немедленно отменяем задачу процессора
        if session.processor_task:
            try:
                logger.info("Cancelling processor task...")
                session.processor_task.cancel()
                # Короткое ожидание отмены
                try:
                    await asyncio.wait_for(session.processor_task, timeout=1.0)
                    logger.info("Processor task cancelled successfully")
                except (asyncio.TimeoutError, asyncio.CancelledError) as e:
                    logger.warning(f"Processor task cancelled with timeout: {e}")
            except Exception as e:
                logger.error(f"Error cancelling processor task: {e}", exc_info=True)
        else:
            logger.warning("No processor task to cancel")

        # Сохраняем файл с полным диалогом
        try:
            logger.info("Saving final dialog file...")
            filepath = await session.save_file()
            logger.info(f"File saved successfully: {filepath}")
        except Exception as e:
            logger.error(f"Failed to save file: {e}", exc_info=True)
            # Все равно отправляем сообщение об ошибке клиенту
            try:
                await session.websocket.send_json(
                    {"type": "error", "message": f"Failed to save file: {str(e)}"}
                )
            except Exception as send_error:
                logger.error(f"Error sending error message: {send_error}")
            return

        # Сообщаем клиенту о завершении с URL для скачивания
        try:
            download_url = f"/download/{session.filename}"
            logger.info(f"Sending done message with download URL: {download_url}")
            await session.websocket.send_json(
                {
                    "type": "done",
                    "file_url": download_url,
                    "message": "Транскрибация завершена. Все данные сохранены.",
                }
            )
            logger.info("Done message sent successfully")
        except Exception as e:
            logger.error(f"Error sending done message: {e}", exc_info=True)

    async def handle_audio_chunk(self, session: Session, data: bytes):
        try:
            # Первый байт - маркер источника (0=микрофон, 1=системный звук)
            if len(data) < 2:
                logger.warning(f"Chunk too small: {len(data)} bytes")
                return

            source = data[0]
            webm_data = data[1:]

            logger.debug(f"Received chunk from source {source}, size {len(webm_data)}")

            if session.processor and session.active:
                await session.processor.process_chunk(source, webm_data)

        except Exception as e:
            logger.error(f"Error handling chunk: {e}")
