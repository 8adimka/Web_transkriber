import asyncio
import os

import aiofiles
from fastapi import WebSocket

from .deepgram_worker import DeepgramWorker
from .utils import get_timestamp_filename, logger

QUEUE_MAX_SIZE = int(os.getenv("QUEUE_MAX_SIZE", 50))
RECORDS_DIR = "records"


class Session:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.audio_queue = asyncio.Queue(maxsize=QUEUE_MAX_SIZE)
        self.transcript_log = []
        self.filename = get_timestamp_filename()
        self.worker = None
        self.worker_task = None
        self.active = True

    def append_transcript(self, text: str):
        self.transcript_log.append(text)

    async def save_file(self) -> str:
        filepath = os.path.join(RECORDS_DIR, self.filename)
        async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
            await f.write(f"TRANSCRIPT DATE: {self.filename}\n")
            await f.write("========================================\n\n")
            for line in self.transcript_log:
                await f.write(f"- {line}\n")
        return filepath


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
        session.worker = DeepgramWorker(
            session.audio_queue, session.websocket, session.append_transcript
        )
        session.worker_task = asyncio.create_task(session.worker.run())

    async def stop_session(self, session: Session):
        session.active = False

        # Сигнализируем worker'у об остановке
        if session.worker:
            session.worker.stop()
            # Отправляем sentinel в очередь, чтобы разблокировать await queue.get()
            await session.audio_queue.put(None)

        if session.worker_task:
            try:
                await asyncio.wait_for(session.worker_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                logger.warning("Worker task forced cancel")

        # Сохраняем файл
        filepath = await session.save_file()

        # Сообщаем клиенту о завершении
        try:
            download_url = f"/download/{session.filename}"
            await session.websocket.send_json(
                {"type": "done", "file_url": download_url}
            )
        except:
            pass

    async def handle_audio_chunk(self, session: Session, data: bytes):
        try:
            # Backpressure: если очередь полна
            if session.audio_queue.full():
                try:
                    await session.websocket.send_json(
                        {"type": "throttle", "action": "slowdown"}
                    )
                    # Дропаем старые пакеты, чтобы не отставать слишком сильно (realtime важнее)
                    try:
                        session.audio_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                except:
                    pass

            await session.audio_queue.put(data)
        except Exception as e:
            logger.error(f"Error handling chunk: {e}")
