import asyncio
import json
import logging
import os
from datetime import datetime
from typing import List

from websockets.client import connect as ws_connect

from .audio_processor import FFmpegStreamer
from .translation_service import translation_service

logger = logging.getLogger("TranslationProcessor")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")


class TranslationProcessor:
    def __init__(self, client_ws, translation_callback):
        self.client_ws = client_ws
        # callback дергаем ТОЛЬКО для финальных фраз, чтобы не спамить в историю
        self.translation_callback = translation_callback
        self.ffmpeg_system = FFmpegStreamer()
        self.is_running = True
        self.translation_history: List[dict] = []
        self.dg_ws = None
        # Очередь маленькая, чтобы не копить лаг
        self.pcm_queue = asyncio.Queue(maxsize=100)
        self.active_tasks: List[asyncio.Task] = []

        self.source_lang = "EN"
        self.target_lang = "RU"

    async def start(self, source_lang: str = "EN", target_lang: str = "RU"):
        self.source_lang = source_lang
        self.target_lang = target_lang

        await translation_service.start()
        await self.ffmpeg_system.start()

        # Чтение из FFmpeg -> Queue
        self.active_tasks.append(
            asyncio.create_task(
                self._ffmpeg_read_loop(self.ffmpeg_system, self.pcm_queue)
            )
        )

        # Queue -> Deepgram
        self.active_tasks.append(
            asyncio.create_task(self._deepgram_sender_loop(self.pcm_queue))
        )

    async def _ffmpeg_read_loop(self, ffmpeg: FFmpegStreamer, queue: asyncio.Queue):
        while self.is_running:
            try:
                # 3200 байт = 100мс аудио (16kHz * 2 байта * 0.1 сек)
                pcm_data = await ffmpeg.read(3200)
                if pcm_data:
                    # Если очередь забилась (лаг), дропаем старое
                    if queue.full():
                        try:
                            queue.get_nowait()
                        except:
                            pass
                    await queue.put(pcm_data)
                else:
                    await asyncio.sleep(0.005)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.1)

    async def _deepgram_sender_loop(self, queue: asyncio.Queue):
        try:
            dg_url = (
                "wss://api.deepgram.com/v1/listen"
                "?encoding=linear16&sample_rate=16000&channels=1"
                f"&model=nova-2&language={self.source_lang.lower()}&punctuate=true&smart_format=true"
                "&endpointing=2500&interim_results=true&speech_final=true"
            )

            async with ws_connect(
                dg_url, extra_headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"}
            ) as ws:
                self.dg_ws = ws
                # Минимальное логирование: убрали info о подключении

                # Параллельно шлем аудио и читаем ответы
                await asyncio.gather(self._send_data(ws, queue), self._recv_data(ws))

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Deepgram connection error: {e}")
            if self.is_running:
                try:
                    await self.client_ws.send_json({"type": "error", "message": str(e)})
                except:
                    pass

    async def _send_data(self, ws, queue):
        try:
            while self.is_running:
                data = await queue.get()
                await ws.send(data)
                queue.task_done()
        except:
            pass

    async def _recv_data(self, ws):
        try:
            async for msg in ws:
                await self._handle_response(msg)
        except:
            pass

    async def _handle_response(self, message: str):
        try:
            data = json.loads(message)
            if data.get("type") == "Results":
                channel = data.get("channel", {})
                alternatives = channel.get("alternatives", [])

                if alternatives:
                    transcript = alternatives[0].get("transcript", "").strip()
                    if not transcript:
                        return

                    is_final = data.get("is_final", False)

                    # ПЕРЕВОД (ТОЛЬКО DEEPL)
                    translated_text = await translation_service.translate(
                        transcript, self.source_lang, self.target_lang
                    )

                    # Логика отправки:
                    # Если is_final - сохраняем в историю и шлем как финал
                    # Если interim - просто шлем на фронт для обновления "на лету"

                    if is_final:
                        # Минимальное логирование: убрали info о финальных фразах
                        # Колбэк только для финала! Чтобы не было спама в файле
                        self.translation_callback(f"{transcript} -> {translated_text}")

                    # Отправляем на фронт (и interim, и final)
                    await self.client_ws.send_json(
                        {
                            "type": "translation",
                            "original": transcript,
                            "translated": translated_text,
                            "is_final": is_final,
                            "timestamp": datetime.now().strftime("%H:%M:%S"),
                        }
                    )

        except Exception as e:
            logger.error(f"Error handling response: {e}")

    async def process_chunk(self, webm_data: bytes):
        # Пишем входные данные (WebM) в FFmpeg
        await self.ffmpeg_system.write(webm_data)

    async def stop(self):
        if not self.is_running:
            return
        self.is_running = False

        # Очищаем очередь, чтобы задачи могли завершиться
        while not self.pcm_queue.empty():
            try:
                self.pcm_queue.get_nowait()
                self.pcm_queue.task_done()
            except:
                break

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

        # Закрываем WebSocket соединение с Deepgram
        try:
            if self.dg_ws:
                await self.dg_ws.close()
        except:
            pass

        # Останавливаем FFmpeg и сервис перевода
        await asyncio.gather(
            self.ffmpeg_system.stop(),
            translation_service.stop(),
            return_exceptions=True,
        )

        # Очищаем список задач
        self.active_tasks.clear()

    def get_translation_history(self) -> List[dict]:
        return self.translation_history.copy()
