import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Callable, List, Optional

from websockets.client import connect as ws_connect

from .translation_service import translation_service

logger = logging.getLogger("UniversalProcessor")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")


class FFmpegStreamer:
    """
    Запускает FFmpeg и читает RAW PCM данные.
    Максимально упрощенная и надежная версия.
    """

    def __init__(self):
        self.process = None
        self._stopped = False

    async def start(self):
        """Запускает процесс FFmpeg, читающий из stdin (pipe:0)"""
        command = [
            "ffmpeg",
            "-i",
            "pipe:0",  # Вход: WebM/Opus из WebSocket
            "-vn",  # Без видео
            "-map",
            "0:a",  # Только аудио
            "-f",
            "s16le",  # Формат: Signed 16-bit Little Endian
            "-ac",
            "1",  # Каналы: 1 (Mono)
            "-ar",
            "16000",  # Частота: 16kHz (стандарт для STT)
            "-acodec",
            "pcm_s16le",
            "-hide_banner",
            "-loglevel",
            "error",  # Только ошибки
            "-flags",
            "low_delay",  # Минимальная задержка
            "pipe:1",  # Выход: stdout
        ]

        self.process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,  # Игнорируем stderr для чистоты, если нужно - поменяем
        )
        # Минимальное логирование: убрали info о старте

    async def write(self, data: bytes):
        """Пишет сжатые данные в FFmpeg"""
        if self.process and self.process.stdin:
            try:
                self.process.stdin.write(data)
                await self.process.stdin.drain()
            except Exception:
                # Игнорируем ошибки записи, если процесс умер (перезапустится)
                pass

    async def read(self, chunk_size: int) -> bytes:
        """Читает разжатые PCM данные"""
        if self.process and self.process.stdout:
            try:
                # readexactly не используем, чтобы не блокироваться намертво
                return await self.process.stdout.read(chunk_size)
            except Exception:
                return b""
        return b""

    async def stop(self):
        if self._stopped:
            return
        self._stopped = True

        if self.process:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
                self.process.terminate()
                await self.process.wait()
            except Exception:
                try:
                    self.process.kill()
                except:
                    pass
            finally:
                self.process = None
        logger.info("FFmpeg streamer stopped")


class UniversalProcessor:
    def __init__(
        self,
        client_ws,
        callback: Callable,
        mode: str = "transcription",
        language: str = "RU",
        source_lang: Optional[str] = None,
        target_lang: Optional[str] = None,
    ):
        self.client_ws = client_ws
        self.callback = callback
        self.mode = mode
        self.language = language if mode == "transcription" else source_lang
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.need_translation = (
            mode == "translation"
            and source_lang
            and target_lang
            and source_lang.lower() != target_lang.lower()
        )

        self.ffmpeg_streams: List[FFmpegStreamer] = []
        self.pcm_queues: List[asyncio.Queue] = []
        self.dg_wss: List[Optional] = []
        self.active_tasks: List[asyncio.Task] = []
        self.is_running = True

        # Для transcription
        self.dialog_segments: List[dict] = []
        self.last_speaker: Optional[str] = None
        self.last_segment_end_time: Optional[datetime] = None
        self.merge_threshold_seconds = 6.0

        # Для translation (accumulation для контекста)
        self.current_phrase: str = ""

        # Настройка потоков
        if self.mode == "transcription":
            # Два потока: me (mic, source=0), interlocutor (system, source=1)
            self.sources = ["me", "interlocutor"]
            for _ in self.sources:
                ffmpeg = FFmpegStreamer()
                self.ffmpeg_streams.append(ffmpeg)
                self.pcm_queues.append(asyncio.Queue(maxsize=100))
                self.dg_wss.append(None)
        else:
            # Один поток: unified (any source)
            self.sources = ["unified"]
            ffmpeg = FFmpegStreamer()
            self.ffmpeg_streams.append(ffmpeg)
            self.pcm_queues.append(asyncio.Queue(maxsize=100))
            self.dg_wss.append(None)

    async def start(self):
        if self.need_translation:
            await translation_service.start()

        # Стартуем FFmpeg
        await asyncio.gather(*(f.start() for f in self.ffmpeg_streams))

        # Для каждого потока: read_loop + deepgram_loop
        for i, source in enumerate(self.sources):
            read_task = asyncio.create_task(
                self._ffmpeg_read_loop(self.ffmpeg_streams[i], self.pcm_queues[i])
            )
            self.active_tasks.append(read_task)
            dg_task = asyncio.create_task(self._deepgram_loop(i, source))
            self.active_tasks.append(dg_task)

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

    async def _deepgram_loop(self, index: int, source: str):
        try:
            # URL Deepgram: diarize только для transcription
            diarize_param = "&diarize=true" if self.mode == "transcription" else ""
            dg_url = (
                "wss://api.deepgram.com/v1/listen"
                "?encoding=linear16&sample_rate=16000&channels=1"
                f"&model=nova-2&language={self.language.lower()}&punctuate=true&smart_format=true"
                "&endpointing=3500&interim_results=true&speech_final=true"  # Увеличено endpointing
                f"{diarize_param}"
            )

            async with ws_connect(
                dg_url, extra_headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"}
            ) as ws:
                self.dg_wss[index] = ws
                sender = asyncio.create_task(
                    self._send_loop(ws, self.pcm_queues[index])
                )
                async for msg in ws:
                    await self._handle_dg_message(source, msg)
                await sender

        except Exception as e:
            logger.error(f"Deepgram error for {source}: {e}")

    async def _send_loop(self, ws, queue):
        while self.is_running:
            try:
                data = await queue.get()
                await ws.send(data)
                queue.task_done()
            except asyncio.CancelledError:
                break

    async def process_chunk(self, source: int, webm_data: bytes):
        if self.mode == "transcription":
            # Route by source
            if source == 0 and len(self.ffmpeg_streams) > 0:
                await self.ffmpeg_streams[0].write(webm_data)  # me (mic)
            elif source == 1 and len(self.ffmpeg_streams) > 1:
                await self.ffmpeg_streams[1].write(webm_data)  # interlocutor (system)
        else:
            # Unified for translation (any source)
            if len(self.ffmpeg_streams) > 0:
                await self.ffmpeg_streams[0].write(webm_data)

    async def _handle_dg_message(self, speaker_source: str, message: str):
        try:
            data = json.loads(message)
            if data.get("type") == "Results":
                alt = data.get("channel", {}).get("alternatives", [])
                if alt:
                    transcript = alt[0].get("transcript", "").strip()
                    if not transcript:
                        return

                    is_final = data.get("is_final", False)
                    current_time = datetime.now()

                    if self.mode == "transcription":
                        # Transcription logic (with speaker)
                        if is_final:
                            item = {
                                "speaker": speaker_source,
                                "text": transcript,
                                "timestamp": current_time,
                            }
                            self._add_to_history(item)
                            self.callback(transcript, speaker_source)

                        await self.client_ws.send_json(
                            {
                                "type": "transcript",
                                "text": transcript,
                                "speaker": speaker_source,
                                "is_final": is_final,
                                "timestamp": current_time.strftime("%H:%M:%S"),
                            }
                        )

                    else:
                        # Translation logic (with replacement for cumulative interim and optional translate)
                        full_phrase = transcript.strip()
                        translated = (
                            await translation_service.translate(
                                full_phrase, self.source_lang, self.target_lang
                            )
                            if self.need_translation
                            else full_phrase
                        )

                        if is_final:
                            self.callback(
                                f"{full_phrase} -> {translated}"
                                if self.need_translation
                                else full_phrase
                            )
                            self.current_phrase = ""
                        else:
                            self.current_phrase = (
                                full_phrase  # Заменяем, так как interim cumulative
                            )

                        await self.client_ws.send_json(
                            {
                                "type": "translation",
                                "original": full_phrase,
                                "translated": translated,
                                "is_final": is_final,
                                "timestamp": current_time.strftime("%H:%M:%S"),
                            }
                        )

        except Exception as e:
            logger.error(f"Error handling DG message: {e}")

    def _add_to_history(self, new_item):
        """Для transcription: склейка per speaker"""
        if (
            self.dialog_segments
            and self.dialog_segments[-1]["speaker"] == new_item["speaker"]
            and (
                new_item["timestamp"] - self.dialog_segments[-1]["timestamp"]
            ).total_seconds()
            < self.merge_threshold_seconds
        ):
            self.dialog_segments[-1]["text"] += f" {new_item['text']}"
            self.dialog_segments[-1]["timestamp"] = new_item["timestamp"]
        else:
            self.dialog_segments.append(new_item)

    async def stop(self):
        if not self.is_running:
            return
        self.is_running = False

        # Очищаем очереди
        for q in self.pcm_queues:
            while not q.empty():
                try:
                    q.get_nowait()
                    q.task_done()
                except:
                    break

        # Отменяем задачи
        for t in self.active_tasks:
            if not t.done():
                t.cancel()

        # Ждём завершения
        if self.active_tasks:
            try:
                await asyncio.wait(self.active_tasks, timeout=2.0)
            except asyncio.TimeoutError:
                pass

        # Закрываем Deepgram WS
        await asyncio.gather(
            *(ws.close() for ws in self.dg_wss if ws),
            return_exceptions=True,
        )

        # Останавливаем FFmpeg и translation если нужно
        stops = [f.stop() for f in self.ffmpeg_streams]
        if self.need_translation:
            stops.append(translation_service.stop())
        await asyncio.gather(*stops, return_exceptions=True)

        self.active_tasks.clear()
        self.current_phrase = ""

    def get_dialog_text(self) -> str:
        """Для transcription: текст диалога"""
        lines = []
        for item in self.dialog_segments:
            sp = "Я" if item["speaker"] == "me" else "Собеседник"
            tm = item["timestamp"].strftime("%H:%M:%S")
            lines.append(f"[{tm}] {sp}: {item['text']}")
        return "\n\n".join(lines)
