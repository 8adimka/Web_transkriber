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
    """
    Процессор для перевода аудио в реальном времени.
    Аудио → Deepgram → Транскрипт → DeepL → Перевод → Фронтенд
    """

    def __init__(self, client_ws, translation_callback):
        self.client_ws = client_ws
        self.translation_callback = translation_callback  # Для сохранения перевода

        # FFmpeg процессор для системного звука (микрофон отключен в режиме перевода)
        self.ffmpeg_system = FFmpegStreamer()

        # Флаги работы
        self.is_running = True

        # Для хранения истории переводов
        self.translation_history: List[dict] = []

        # Deepgram соединение
        self.dg_ws = None

        # Очередь для буферизации PCM данных
        self.pcm_queue = asyncio.Queue(maxsize=100)

        # Для отслеживания активных задач
        self.active_tasks: List[asyncio.Task] = []
        self.session_start_time = datetime.now()

        # Настройки перевода
        self.source_lang = "EN"  # Язык оригинала (можно менять)
        self.target_lang = "RU"  # Язык перевода

        # Для interim результатов
        self.last_interim_text = ""
        self.last_interim_translation = ""

    async def start(self, source_lang: str = "EN", target_lang: str = "RU"):
        """Запускает процессор перевода"""
        self.source_lang = source_lang
        self.target_lang = target_lang

        # Запускаем сервис перевода
        await translation_service.start()

        # Запускаем FFmpeg процессор
        await self.ffmpeg_system.start()

        # Запускаем задачу чтения из FFmpeg
        self.active_tasks.append(
            asyncio.create_task(
                self._ffmpeg_read_loop("system", self.ffmpeg_system, self.pcm_queue)
            )
        )

        # Запускаем Deepgram соединение
        self.active_tasks.append(
            asyncio.create_task(self._deepgram_sender_loop(self.pcm_queue))
        )

    async def _ffmpeg_read_loop(
        self, source: str, ffmpeg: FFmpegStreamer, queue: asyncio.Queue
    ):
        """Непрерывно читает PCM данные из FFmpeg и помещает в очередь"""
        logger.info(f"Starting FFmpeg read loop for {source}")
        while self.is_running:
            try:
                # Читаем PCM данные (3200 байт = 100ms при 16kHz 16-bit mono)
                pcm_data = await ffmpeg.read(3200)
                if pcm_data:
                    logger.debug(f"FFmpeg {source} produced {len(pcm_data)} bytes PCM")
                    await queue.put(pcm_data)
                else:
                    await asyncio.sleep(0.001)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error reading FFmpeg for {source}: {e}")
                await asyncio.sleep(0.1)

    async def _deepgram_sender_loop(self, queue: asyncio.Queue):
        """Устанавливает соединение с Deepgram и отправляет данные из очереди"""
        try:
            dg_url = (
                "wss://api.deepgram.com/v1/listen"
                "?encoding=linear16&sample_rate=16000&channels=1"
                f"&model=nova-2&language={self.source_lang}&punctuate=true&smart_format=true"
                "&endpointing=300&interim_results=true"
            )

            async with ws_connect(
                dg_url, extra_headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"}
            ) as ws:
                self.dg_ws = ws
                logger.info(
                    f"Deepgram connection established for translation (source: {self.source_lang})"
                )

                # Задача для отправки данных
                send_task = asyncio.create_task(self._send_data_to_deepgram(ws, queue))
                # Задача для приема ответов
                receive_task = asyncio.create_task(self._receive_from_deepgram(ws))

                # Ожидаем завершения обеих задач
                await asyncio.gather(send_task, receive_task)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Deepgram connection error: {e}")
            if self.is_running:
                try:
                    await self.client_ws.send_json(
                        {
                            "type": "error",
                            "message": f"Deepgram error: {str(e)}",
                        }
                    )
                except:
                    pass

    async def _send_data_to_deepgram(self, ws, queue: asyncio.Queue):
        """Отправляет PCM данные из очереди в Deepgram"""
        logger.info("Starting Deepgram sender for translation")
        try:
            while self.is_running:
                pcm_data = await queue.get()
                if pcm_data:
                    logger.debug(f"Sending {len(pcm_data)} bytes to Deepgram")
                    await ws.send(pcm_data)
                    queue.task_done()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error sending to Deepgram: {e}")

    async def _receive_from_deepgram(self, ws):
        """Принимает ответы от Deepgram и переводит их"""
        logger.info("Starting Deepgram receiver for translation")
        try:
            async for message in ws:
                await self._handle_deepgram_response(message)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error receiving from Deepgram: {e}")

    async def process_chunk(self, webm_data: bytes):
        """Обрабатывает входящий чанк аудио (только системный звук в режиме перевода)"""
        await self.ffmpeg_system.write(webm_data)

    async def _handle_deepgram_response(self, message: str):
        """Обрабатывает ответ от Deepgram, переводит и отправляет на фронтенд"""
        try:
            data = json.loads(message)
            msg_type = data.get("type")

            logger.debug(f"Deepgram message type: {msg_type}")

            if msg_type == "Results":
                channel = data.get("channel", {})
                alternatives = channel.get("alternatives", [])

                if alternatives:
                    transcript = alternatives[0].get("transcript", "")
                    is_final = data.get("is_final", False)

                    # Фильтруем пустые транскрипты
                    if not transcript.strip():
                        logger.debug("Deepgram: empty transcript, skipping")
                        return

                    logger.info(
                        f"Deepgram: {'FINAL' if is_final else 'interim'} transcript: {transcript}"
                    )

                    # Переводим текст
                    translated = await translation_service.translate(
                        transcript,
                        target_lang=self.target_lang,
                        source_lang=self.source_lang,
                    )

                    # Сохраняем в историю если final
                    if is_final:
                        current_time = datetime.now()

                        # Создаем элемент истории
                        history_item = {
                            "original": transcript,
                            "translated": translated,
                            "timestamp": current_time,
                            "source_lang": self.source_lang,
                            "target_lang": self.target_lang,
                        }

                        self.translation_history.append(history_item)

                        # Сохраняем через callback
                        self.translation_callback(translated, "translation")

                        # Сбрасываем interim
                        self.last_interim_text = ""
                        self.last_interim_translation = ""

                    # Отправляем на фронтенд
                    await self.client_ws.send_json(
                        {
                            "type": "translation",
                            "original": transcript,
                            "translated": translated,
                            "is_final": is_final,
                            "timestamp": datetime.now().strftime("%H:%M:%S"),
                            "source_lang": self.source_lang,
                            "target_lang": self.target_lang,
                        }
                    )
                else:
                    logger.debug("Deepgram: no alternatives in results")

            elif msg_type == "Metadata":
                logger.debug("Deepgram: metadata received")
            else:
                logger.debug(f"Deepgram: unknown message type {msg_type}")

        except Exception as e:
            logger.error(f"Error handling Deepgram response: {e}")

    async def stop(self):
        """Останавливает процессор перевода"""
        logger.info("Stopping TranslationProcessor immediately")
        self.is_running = False

        # Немедленно отменяем все активные задачи без ожидания
        if self.active_tasks:
            logger.info(f"Cancelling {len(self.active_tasks)} active tasks...")
            for task in self.active_tasks:
                task.cancel()
            logger.info("Tasks cancelled (not waiting for completion)")

        # Очищаем очередь PCM данных
        logger.info("Clearing PCM queue...")
        while not self.pcm_queue.empty():
            try:
                self.pcm_queue.get_nowait()
                self.pcm_queue.task_done()
            except asyncio.QueueEmpty:
                break

        # Закрываем Deepgram соединение без ожидания
        try:
            if self.dg_ws:
                self.dg_ws.close()
        except Exception as e:
            logger.debug(f"Error closing Deepgram connection (expected): {e}")

        # Останавливаем FFmpeg процесс
        try:
            self.ffmpeg_system.stop()
        except Exception as e:
            logger.error(f"Error stopping FFmpeg: {e}")

        # Останавливаем сервис перевода
        await translation_service.stop()

        logger.info("TranslationProcessor stopped immediately")

    def get_translation_history(self) -> List[dict]:
        """Возвращает историю переводов"""
        return self.translation_history.copy()
