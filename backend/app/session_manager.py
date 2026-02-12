import asyncio
import logging
import os

import aiofiles
from fastapi import WebSocket

from .dialogue_processor import DialogueProcessor
from .translation_processor import TranslationProcessor
from .utils import get_timestamp_filename

RECORDS_DIR = "records"


class Session:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.transcript_log = []
        self.speaker_log = []
        self.translation_log = []
        self.filename = get_timestamp_filename()
        self.processor = None
        self.processor_task = None
        self.active = True
        self.mode = "transcription"
        self.stopped = False

    def append_transcript(self, text, speaker=""):
        self.transcript_log.append(text)
        self.speaker_log.append(speaker)

    def append_translation(self, text):
        self.translation_log.append(text)

    async def save_file(self):
        os.makedirs(RECORDS_DIR, exist_ok=True)
        path = os.path.join(RECORDS_DIR, self.filename)
        try:
            async with aiofiles.open(path, "w", encoding="utf-8") as f:
                if self.mode == "transcription":
                    await f.write("ТРАНСКРИПЦИЯ\n\n")
                    # Если есть процессор DialogueProcessor, используем его метод для получения текста с временем
                    if isinstance(self.processor, DialogueProcessor):
                        dialog_text = self.processor.get_dialog_text()
                        await f.write(dialog_text)
                    else:
                        # Старый способ (без времени)
                        for t, s in zip(self.transcript_log, self.speaker_log):
                            sp = "Я" if s == "me" else "Собеседник"
                            await f.write(f"{sp}: {t}\n\n")
                    logger = logging.getLogger("Session")
                    logger.info(f"Файл транскрипции сохранен: {path}")
                else:
                    # Режим перевода - файл не сохраняем (по требованию пользователя)
                    # Возвращаем None, чтобы фронтенд не показывал ссылку на скачивание
                    return None
            return path
        except Exception as e:
            logger = logging.getLogger("Session")
            logger.error(f"Ошибка сохранения файла: {e}")
            return None


class SessionManager:
    def __init__(self):
        self.active_sessions = {}

    def create(self, websocket: WebSocket) -> Session:
        s = Session(websocket)
        self.active_sessions[id(websocket)] = s
        return s

    def remove(self, websocket: WebSocket):
        if id(websocket) in self.active_sessions:
            del self.active_sessions[id(websocket)]

    async def start_transcription_worker(self, session: Session, language: str = "RU"):
        session.processor = DialogueProcessor(
            session.websocket, session.append_transcript, language
        )
        session.mode = "transcription"
        session.processor_task = asyncio.create_task(session.processor.start())

    async def start_translation_worker(
        self, session: Session, source_lang="EN", target_lang="RU"
    ):
        session.processor = TranslationProcessor(
            session.websocket, session.append_translation
        )
        session.mode = "translation"
        session.processor_task = asyncio.create_task(
            session.processor.start(source_lang, target_lang)
        )

    async def stop_session(self, session: Session):
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

        path = await session.save_file()
        msg = {"type": "done", "message": "Готово"}
        if path:
            msg["file_url"] = f"/download/{session.filename}"
            logger.info(f"Файл доступен для скачивания: {msg['file_url']}")
        else:
            logger.info("Файл не сохранен (режим перевода или ошибка)")

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
            if session.mode == "transcription":
                await session.processor.process_chunk(source, webm)
            elif session.mode == "translation":
                # В режиме перевода принимаем как микрофон (0), так и системный звук (1)
                # TranslationProcessor ожидает только один канал, поэтому передаем webm независимо от source
                if isinstance(session.processor, TranslationProcessor):
                    await session.processor.process_chunk(webm)
