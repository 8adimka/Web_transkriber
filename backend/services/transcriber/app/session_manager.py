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
        self.stop_lock = asyncio.Lock()

    def append_transcript(self, text: str, speaker: str = ""):
        self.transcript_log.append(text)
        self.speaker_log.append(speaker)

    def append_translation(self, text: str):
        self.translation_log.append(text)

    def build_content(self) -> str:
        """Only finalized segments are persisted; interim updates remain transient."""
        if self.mode == "translation":
            return "TRANSLATION\n\n" + "\n\n".join(self.translation_log) if self.translation_log else ""
        if not self.transcript_log:
            return ""
        if isinstance(self.processor, UniversalProcessor):
            content = self.processor.get_dialog_text()
        else:
            content = "\n\n".join(
                f"{'Я' if speaker == 'me' else 'Собеседник'}: {text}"
                for text, speaker in zip(self.transcript_log, self.speaker_log)
            )
        return "ТРАНСКРИПЦИЯ\n\n" + content

    async def save_to_db(
        self, language: str = "RU", translate_to: Optional[str] = None
    ) -> Optional[int]:
        """Persist transcription or translation after provider finalization."""
        content = self.build_content()
        if not content:
            return None
        if not self.user_id:
            raise ValueError("Cannot save text without an authenticated owner")

        def persist():
            from .crud import create_transcription
            from .database import SessionLocal

            db = SessionLocal()
            try:
                record = create_transcription(
                    db=db, user_id=int(self.user_id), filename=self.filename,
                    content=content, orig_language=language,
                    translate_to=translate_to, file_size=len(content.encode("utf-8")),
                )
                return record.id
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

        return await asyncio.to_thread(persist)


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
        if session.processor is not None or session.stopped:
            raise ValueError("This recording session has already started")
        session.mode = mode
        # Преобразуем user_id в int, если он есть
        user_id_int = None
        if session.user_id:
            try:
                user_id_int = int(session.user_id)
            except (ValueError, TypeError):
                logger = logging.getLogger("SessionManager")
                logger.warning(f"Invalid user_id format: {session.user_id}")

        session.processor = UniversalProcessor(
            session.websocket,
            session.append_transcript
            if mode == "transcription"
            else session.append_translation,
            mode=mode,
            user_id=user_id_int,
            **kwargs,
        )
        session.processor_task = asyncio.create_task(session.processor.start())

    async def stop_session(
        self, session: Session, language: str = "RU", translate_to: Optional[str] = None
    ):
        async with session.stop_lock:
            if session.stopped:
                return
            session.stopped = True
            session.active = False
            incomplete = False
            if session.processor_task:
                try:
                    await asyncio.wait_for(asyncio.shield(session.processor_task), timeout=10)
                except Exception:
                    incomplete = True
                    session.processor_task.cancel()
                    await asyncio.gather(session.processor_task, return_exceptions=True)
            if session.processor:
                try:
                    await session.processor.stop()
                    incomplete = incomplete or session.processor.stop_incomplete
                except Exception:
                    incomplete = True

            has_text = bool(session.translation_log if session.mode == "translation"
                            else session.transcript_log)
            transcription_id = None
            try:
                transcription_id = await session.save_to_db(
                    language=language, translate_to=translate_to
                )
            except Exception:
                logging.getLogger("SessionManager").warning("Could not save finalized text")
                try:
                    await session.websocket.send_json({
                        "type": "error", "code": "save_failed",
                        "message": "The text could not be saved. Download a local copy before leaving.",
                    })
                except Exception:
                    pass

            msg = {
                "type": "done", "message": "Done", "saved": transcription_id is not None,
                "empty": not has_text, "incomplete": incomplete,
            }
            if transcription_id is not None:
                msg["transcription_id"] = str(transcription_id)
                msg["download_url"] = f"/transcriptions/{transcription_id}/download"
            try:
                await session.websocket.send_json(msg)
            except Exception:
                logging.getLogger("SessionManager").debug("Client disconnected before completion")

    async def handle_audio_chunk(self, session: Session, data: bytes):
        if len(data) < 2:
            return
        source = data[0]
        webm = data[1:]

        if session.processor and session.active:
            if session.processor_task:
                await session.processor_task
            await session.processor.process_chunk(source, webm)
