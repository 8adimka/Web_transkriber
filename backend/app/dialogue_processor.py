import asyncio
import json
import logging
import os
from datetime import datetime
from typing import List, Optional

from websockets.client import connect as ws_connect

from .audio_processor import FFmpegStreamer

logger = logging.getLogger("DialogueProcessor")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")


class DialogueProcessor:
    def __init__(self, client_ws, transcript_callback, language: str = "RU"):
        self.client_ws = client_ws
        self.transcript_callback = transcript_callback
        self.language = language

        self.ffmpeg_me = FFmpegStreamer()
        self.ffmpeg_interlocutor = FFmpegStreamer()
        self.is_running = True
        self.dialog_segments: List[dict] = []

        # Для склейки реплик
        self.last_speaker: Optional[str] = None
        self.last_segment_end_time: Optional[datetime] = None
        self.merge_threshold_seconds = 2.0

        self.active_tasks: List[asyncio.Task] = []

    async def start(self):
        await self.ffmpeg_me.start()
        await self.ffmpeg_interlocutor.start()

        # Запускаем пайплайны для двух каналов
        self.active_tasks.append(
            asyncio.create_task(self._process_channel("me", self.ffmpeg_me))
        )
        self.active_tasks.append(
            asyncio.create_task(
                self._process_channel("interlocutor", self.ffmpeg_interlocutor)
            )
        )

    async def _process_channel(self, source: str, ffmpeg: FFmpegStreamer):
        """Полный цикл обработки канала: Чтение -> Deepgram -> Клиент"""
        queue = asyncio.Queue(maxsize=100)

        # 1. Читаем FFmpeg
        read_task = asyncio.create_task(self._ffmpeg_read_loop(ffmpeg, queue))

        # 2. Шлем в Deepgram
        try:
            dg_url = (
                "wss://api.deepgram.com/v1/listen"
                "?encoding=linear16&sample_rate=16000&channels=1"
                f"&model=nova-2&language={self.language.lower()}&punctuate=true&smart_format=true"
                "&endpointing=5000&diarize=true&interim_results=true&speech_final=true"
            )

            async with ws_connect(
                dg_url, extra_headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"}
            ) as ws:
                sender = asyncio.create_task(self._send_loop(ws, queue))

                # 3. Читаем ответы
                async for msg in ws:
                    await self._handle_dg_message(source, msg)

                await sender

        except Exception as e:
            logger.error(f"Channel {source} error: {e}")
        finally:
            read_task.cancel()

    async def _ffmpeg_read_loop(self, ffmpeg: FFmpegStreamer, queue: asyncio.Queue):
        while self.is_running:
            data = await ffmpeg.read(3200)
            if data:
                if queue.full():
                    try:
                        queue.get_nowait()
                    except:
                        pass
                await queue.put(data)
            else:
                await asyncio.sleep(0.005)

    async def _send_loop(self, ws, queue):
        while self.is_running:
            data = await queue.get()
            await ws.send(data)
            queue.task_done()

    async def process_chunk(self, source: int, webm_data: bytes):
        # Маршрутизация входящих WebM чанков в нужный FFmpeg
        if source == 0:
            await self.ffmpeg_me.write(webm_data)
        elif source == 1:
            await self.ffmpeg_interlocutor.write(webm_data)

    async def _handle_dg_message(self, source: str, message: str):
        try:
            data = json.loads(message)
            if data.get("type") == "Results":
                alt = data.get("channel", {}).get("alternatives", [])
                if alt:
                    transcript = alt[0].get("transcript", "")
                    if not transcript.strip():
                        return

                    is_final = data.get("is_final", False)

                    # Сохраняем ТОЛЬКО финал
                    if is_final:
                        current_time = datetime.now()
                        item = {
                            "speaker": source,
                            "text": transcript,
                            "timestamp": current_time,
                        }
                        self._add_to_history(item)
                        self.transcript_callback(transcript, source)

                    # Шлем на клиент (и interim, и final)
                    await self.client_ws.send_json(
                        {
                            "type": "transcript",
                            "text": transcript,
                            "speaker": source,
                            "is_final": is_final,
                            "timestamp": datetime.now().strftime("%H:%M:%S"),
                        }
                    )
        except Exception:
            pass

    def _add_to_history(self, new_item):
        """Добавляет в историю с простейшей склейкой"""
        if (
            self.dialog_segments
            and self.dialog_segments[-1]["speaker"] == new_item["speaker"]
            and (
                new_item["timestamp"] - self.dialog_segments[-1]["timestamp"]
            ).total_seconds()
            < 2.0
        ):
            self.dialog_segments[-1]["text"] += f" {new_item['text']}"
            self.dialog_segments[-1]["timestamp"] = new_item["timestamp"]
        else:
            self.dialog_segments.append(new_item)

    async def stop(self):
        if not self.is_running:
            return
        self.is_running = False

        # Отменяем все задачи
        for t in self.active_tasks:
            if not t.done():
                t.cancel()

        # Ждем завершения задач с таймаутом
        if self.active_tasks:
            try:
                await asyncio.wait(self.active_tasks, timeout=2.0)
            except asyncio.TimeoutError:
                pass

        # Останавливаем FFmpeg процессы
        await asyncio.gather(
            self.ffmpeg_me.stop(),
            self.ffmpeg_interlocutor.stop(),
            return_exceptions=True,
        )

        # Очищаем список задач
        self.active_tasks.clear()

    def get_dialog_text(self) -> str:
        lines = []
        for item in self.dialog_segments:
            sp = "Я" if item["speaker"] == "me" else "Собеседник"
            tm = item["timestamp"].strftime("%H:%M:%S")
            lines.append(f"[{tm}] {sp}: {item['text']}")
        return "\n\n".join(lines)
