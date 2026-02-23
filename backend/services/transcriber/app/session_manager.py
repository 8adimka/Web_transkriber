import asyncio
import logging
from typing import Optional

from fastapi import WebSocket

from .audio_processor import UniversalProcessor
from .utils import get_timestamp_filename


class Session:
    def __init__(self, websocket: WebSocket, user_id: Optional[str] = None):
        self.websocket = websocket
        self.user_id = user_id
        self.transcript_log = []
        self.speaker_log = []
        self.translation_log = []
        self.filename = get_timestamp_filename()
        self.processor: Optional[UniversalProcessor] = None
        self.processor_task: Optional[asyncio.Task] = None
        self.active = True
        self.mode = "transcription"
        self.stopped = False

    def append_transcript(self, text: str, speaker: str = ""):
        self.transcript_log.append(text)
        self.speaker_log.append(speaker)

    def append_translation(self, text: str):
        self.translation_log.append(text)

    async def save_to_db(
        self, language: str = "RU", translate_to: Optional[str] = None
    ) -> Optional[int]:
        """Сохраняет транскрипцию в БД и возвращает ID записи"""
        if self.mode != "transcription":
            return None  # Для перевода не сохраняем в БД
        if not self.transcript_log:
            return None  # Не сохраняем пустую транскрипцию

        try:
            # Получаем текст транскрипции
            content = "ТРАНСКРИПЦИЯ\n\n"
            if self.processor and isinstance(self.processor, UniversalProcessor):
                content += self.processor.get_dialog_text()
            else:
                # Старый способ (без времени)
                for t, s in zip(self.transcript_log, self.speaker_log):
                    sp = "Я" if s == "me" else "Собеседник"
                    content += f"{sp}: {t}\n\n"

            # Сохраняем в БД (синхронно, но в отдельном потоке)
            from .crud import create_transcription
            from .database import SessionLocal

            db = SessionLocal()
            try:
                transcription = create_transcription(
                    db=db,
                    user_id=int(self.user_id) if self.user_id else 0,
                    filename=self.filename,
                    content=content,
                    orig_language=language,
                    translate_to=translate_to,
                    file_size=len(content.encode("utf-8")),
                )
                logger = logging.getLogger("Session")
                transcription_id = transcription.id  # Получаем значение ID
                logger.info(f"Транскрипция сохранена в БД: ID={transcription_id}")
                return transcription_id
            finally:
                db.close()

        except Exception as e:
            logger = logging.getLogger("Session")
            logger.error(f"Ошибка сохранения транскрипции в БД: {e}")
            return None


class SessionManager:
    def __init__(self):
        self.active_sessions = {}

    def create(self, websocket: WebSocket, user_id: Optional[str] = None) -> Session:
        s = Session(websocket, user_id)
        self.active_sessions[id(websocket)] = s
        return s

    def remove(self, websocket: WebSocket):
        if id(websocket) in self.active_sessions:
            del self.active_sessions[id(websocket)]

    async def start_worker(
        self, session: Session, mode: str = "transcription", **kwargs
    ):
        session.mode = mode
        session.processor = UniversalProcessor(
            session.websocket,
            session.append_transcript
            if mode == "transcription"
            else session.append_translation,
            mode=mode,
            **kwargs,
        )
        session.processor_task = asyncio.create_task(session.processor.start())

    async def stop_session(
        self, session: Session, language: str = "RU", translate_to: Optional[str] = None
    ):
        if session.stopped:
            return
        session.stopped = True
        session.active = False

        logger = logging.getLogger("SessionManager")
        logger.info(f"Остановка сессии {session.filename}")

        if session.processor:
            await session.processor.stop()
        if session.processor_task:
            session.processor_task.cancel()

        # Сохраняем в БД вместо файла
        transcription_id = await session.save_to_db(
            language=language, translate_to=translate_to
        )
        msg = {"type": "done", "message": "Готово"}
        if transcription_id:
            msg["transcription_id"] = str(transcription_id)
            # Формируем URL для скачивания с токеном
            # Токен будет добавлен фронтендом при скачивании
            msg["download_url"] = f"/transcriptions/{transcription_id}/download"
            logger.info(f"Транскрипция сохранена в БД: ID={transcription_id}")
        else:
            logger.info("Транскрипция не сохранена (режим перевода или ошибка)")

        try:
            await session.websocket.send_json(msg)
            logger.info("Сообщение 'done' отправлено клиенту")
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение 'done': {e}")

    async def handle_audio_chunk(self, session: Session, data: bytes):
        if len(data) < 2:
            return
        source = data[0]
        webm = data[1:]

        if session.processor and session.active:
            await session.processor.process_chunk(source, webm)
