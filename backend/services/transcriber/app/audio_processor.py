import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Callable, List, Optional

from websockets.client import connect as ws_connect

from backend.shared.token_tracker import get_token_tracker

from .translation_service import TranslationService

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

    async def finish_input(self):
        """Signal EOF while keeping stdout alive for the last decoded samples."""
        if self.process and self.process.stdin:
            try:
                await self.process.stdin.drain()
                self.process.stdin.close()
                await self.process.stdin.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                pass

    async def stop(self):
        if self._stopped:
            return
        self._stopped = True
        process = self.process
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
        except ProcessLookupError:
            pass
        finally:
            self.process = None



class UniversalProcessor:
    def __init__(
        self,
        client_ws,
        callback: Callable,
        mode: str = "transcription",
        language: str = "RU",
        source_lang: Optional[str] = None,
        target_lang: Optional[str] = None,
        user_id: Optional[int] = None,
    ):
        self.client_ws = client_ws
        self.callback = callback
        self.mode = mode
        # Для режима транскрипции source_lang = language, target_lang = target_lang
        if mode == "transcription":
            self.source_lang = language
            self.target_lang = target_lang if target_lang else ""
            self.language = language  # язык для DeepGram
        else:
            self.source_lang = source_lang if source_lang else ""
            self.target_lang = target_lang if target_lang else ""
            self.language = source_lang if source_lang else "RU"
        self.user_id = user_id
        # Перевод нужен, если указаны оба языка и они отличаются
        self.need_translation = (
            self.source_lang
            and self.target_lang
            and self.source_lang.lower() != self.target_lang.lower()
        )

        self.ffmpeg_streams: List[FFmpegStreamer] = []
        self.pcm_queues: List[asyncio.Queue] = []
        self.dg_wss: List = []
        self.active_tasks: List[asyncio.Task] = []
        self.is_running = True
        self._stopping = False
        self._stop_task: Optional[asyncio.Task] = None
        self.read_tasks: List[asyncio.Task] = []
        self.deepgram_tasks: List[asyncio.Task] = []
        self.sender_tasks: List[asyncio.Task] = []
        self.stop_incomplete = False
        self.processing_error = False
        self.stop_timeout = 20.0
        # Session-owned client and cache: stopping another session cannot close it.
        self.translation_service = TranslationService()

        # Для transcription
        self.dialog_segments: List[dict] = []
        self.last_speaker: Optional[str] = None
        self.last_segment_end_time: Optional[datetime] = None
        self.merge_threshold_seconds = 6.0

        # Для translation (accumulation для контекста)
        self.current_phrase: str = ""

        # Token tracker
        self.token_tracker = get_token_tracker()

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
            await self.translation_service.start()

        # Стартуем FFmpeg
        await asyncio.gather(*(f.start() for f in self.ffmpeg_streams))

        # Для каждого потока: read_loop + deepgram_loop
        for i, source in enumerate(self.sources):
            read_task = asyncio.create_task(
                self._ffmpeg_read_loop(self.ffmpeg_streams[i], self.pcm_queues[i])
            )
            self.active_tasks.append(read_task)
            self.read_tasks.append(read_task)
            dg_task = asyncio.create_task(self._deepgram_loop(i, source))
            self.active_tasks.append(dg_task)
            self.deepgram_tasks.append(dg_task)

    async def _ffmpeg_read_loop(self, ffmpeg: FFmpegStreamer, queue: asyncio.Queue):
        while True:
            data = await ffmpeg.read(3200)
            if not data:
                break
            # Backpressure preserves pending PCM instead of dropping its tail.
            await queue.put(data)
        await queue.put(None)  # EOF: sender finalizes only after all queued PCM.

    async def _deepgram_loop(self, index: int, source: str):
        sender = None
        try:
            diarize_param = "&diarize=true" if self.mode == "transcription" else ""
            dg_url = (
                "wss://api.deepgram.com/v1/listen"
                "?encoding=linear16&sample_rate=16000&channels=1"
                f"&model=nova-2&language={self.language.lower()}&punctuate=true&smart_format=true"
                "&endpointing=3500&interim_results=true&speech_final=true"
                f"{diarize_param}"
            )
            async with ws_connect(
                dg_url, extra_headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"},
                open_timeout=10, close_timeout=2,
            ) as ws:
                self.dg_wss[index] = ws
                sender = asyncio.create_task(self._send_loop(ws, self.pcm_queues[index]))
                self.sender_tasks.append(sender)
                async for msg in ws:
                    await self._handle_dg_message(source, msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.processing_error = True
            logger.warning("Speech provider connection failed for source %s", source)
            try:
                await self.client_ws.send_json({
                    "type": "error", "code": "provider_error",
                    "message": "The speech service connection was interrupted.",
                })
            except Exception:
                pass
        finally:
            if sender is not None:
                if not sender.done():
                    sender.cancel()
                await asyncio.gather(sender, return_exceptions=True)

    async def _send_loop(self, ws, queue):
        try:
            while True:
                data = await queue.get()
                try:
                    if data is None:
                        # Deepgram returns its remaining final results, then closes.
                        # https://developers.deepgram.com/docs/close-stream
                        await ws.send(json.dumps({"type": "CloseStream"}))
                        return
                    await ws.send(data)
                finally:
                    queue.task_done()
        except asyncio.CancelledError:
            raise
        except Exception:
            self.processing_error = True
            await ws.close()
            raise

    async def process_chunk(self, source: int, webm_data: bytes):
        if self._stopping:
            return
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
                            # Если нужен перевод, переводим текст
                            final_text = transcript
                            if self.need_translation:
                                # source_lang и target_lang гарантированно не None, т.к. need_translation истинно
                                final_text = await self.translation_service.translate(
                                    transcript,
                                    self.source_lang,  # type: ignore
                                    self.target_lang,  # type: ignore
                                    user_id=self.user_id,
                                )

                            item = {
                                "speaker": speaker_source,
                                "text": final_text,
                                "timestamp": current_time,
                            }
                            self._add_to_history(item)
                            self.callback(final_text, speaker_source)

                            # Трекинг использования DeepGram
                            if self.user_id:
                                # Оцениваем длину аудио: примерно 2.5 секунды на финальный сегмент
                                # (endpointing=3500 означает сегменты длиной ~3.5 секунды, но консервативно 2.5)
                                audio_seconds = 2.5
                                metadata = {
                                    "transcript": transcript,
                                    "speaker": speaker_source,
                                    "segment_length": audio_seconds,
                                }
                                await self.token_tracker.track_deepgram_usage(
                                    user_id=self.user_id,
                                    audio_seconds=audio_seconds,
                                    metadata=metadata,
                                )

                            # Отправляем клиенту текст (переведённый, если требуется)
                            text_to_send = final_text
                        else:
                            # Interim результат - отправляем оригинал (перевод не применяем)
                            text_to_send = transcript

                        await self.client_ws.send_json(
                            {
                                "type": "transcript",
                                "text": text_to_send,
                                "speaker": speaker_source,
                                "is_final": is_final,
                                "timestamp": current_time.strftime("%H:%M:%S"),
                            }
                        )

                    else:
                        # Translation logic (with replacement for cumulative interim and optional translate)
                        full_phrase = transcript.strip()
                        translated = (
                            await self.translation_service.translate(
                                full_phrase,
                                self.source_lang,
                                self.target_lang,
                                user_id=self.user_id,
                            )
                            if self.need_translation
                            else full_phrase
                        )

                        # Трекинг использования DeepGram для перевода (в любом случае)
                        if self.user_id and is_final:
                            # Оцениваем длину аудио: примерно 2.5 секунды на финальный сегмент
                            audio_seconds = 2.5
                            metadata = {
                                "transcript": full_phrase,
                                "translated": translated
                                if self.need_translation
                                else None,
                                "mode": "translation",
                                "segment_length": audio_seconds,
                            }
                            await self.token_tracker.track_deepgram_usage(
                                user_id=self.user_id,
                                audio_seconds=audio_seconds,
                                metadata=metadata,
                            )

                        if is_final:
                            self.callback(translated)
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

        except Exception:
            self.processing_error = True
            logger.warning("Could not process a speech provider message")

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
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._finish())
        await asyncio.shield(self._stop_task)

    async def _finish(self):
        self._stopping = True

        async def drain():
            await asyncio.gather(*(stream.finish_input() for stream in self.ffmpeg_streams))
            # Readers emit EOF sentinels; senders issue CloseStream; receiver loops
            # stay alive for final provider results and translation callbacks.
            if self.active_tasks:
                await asyncio.gather(*self.active_tasks)

        try:
            await asyncio.wait_for(drain(), timeout=self.stop_timeout)
        except Exception:
            self.stop_incomplete = True
            logger.warning("Audio finalization did not complete; preserving received text")
        finally:
            self.stop_incomplete = self.stop_incomplete or self.processing_error
            self.is_running = False
            tasks = self.active_tasks + self.sender_tasks
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            sockets = [ws for ws in self.dg_wss if ws is not None]
            if sockets:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*(ws.close() for ws in sockets), return_exceptions=True),
                        timeout=3.0,
                    )
                except asyncio.TimeoutError:
                    pass
            await asyncio.gather(*(stream.stop() for stream in self.ffmpeg_streams),
                                 return_exceptions=True)
            if self.need_translation:
                await self.translation_service.stop()
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
