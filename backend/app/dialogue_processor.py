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
    """
    Улучшенный процессор диалогов с:
    1. Реальным временем (HH:MM:SS)
    2. Гарантированным завершением всех транскрибаций
    3. Объединением смежных реплик одного говорящего
    4. Простой и надежной архитектурой
    """

    def __init__(self, client_ws, transcript_callback):
        self.client_ws = client_ws
        self.transcript_callback = transcript_callback

        # Два отдельных FFmpeg процессора для каждого источника
        self.ffmpeg_me = FFmpegStreamer()
        self.ffmpeg_interlocutor = FFmpegStreamer()

        # Флаги работы
        self.is_running = True

        # Для хранения диалога в хронологическом порядке с реальным временем
        self.dialog_segments: List[dict] = []

        # Для объединения смежных реплик одного говорящего
        self.last_speaker: Optional[str] = None
        self.last_segment_end_time: Optional[datetime] = None
        self.merge_threshold_seconds = (
            2.0  # Объединять реплики, если пауза меньше 2 секунд
        )

        # Deepgram соединения
        self.dg_ws_me = None
        self.dg_ws_interlocutor = None

        # Очереди для буферизации PCM данных
        self.pcm_queue_me = asyncio.Queue(maxsize=100)
        self.pcm_queue_interlocutor = asyncio.Queue(maxsize=100)

        # Для отслеживания активных задач
        self.active_tasks: List[asyncio.Task] = []
        self.session_start_time = datetime.now()

    async def start(self):
        """Запускает процессоры"""
        await self.ffmpeg_me.start()
        await self.ffmpeg_interlocutor.start()

        # Запускаем задачи чтения из FFmpeg
        self.active_tasks.append(
            asyncio.create_task(
                self._ffmpeg_read_loop("me", self.ffmpeg_me, self.pcm_queue_me)
            )
        )
        self.active_tasks.append(
            asyncio.create_task(
                self._ffmpeg_read_loop(
                    "interlocutor",
                    self.ffmpeg_interlocutor,
                    self.pcm_queue_interlocutor,
                )
            )
        )

        # Запускаем Deepgram соединения
        self.active_tasks.append(
            asyncio.create_task(self._deepgram_sender_loop("me", self.pcm_queue_me))
        )
        self.active_tasks.append(
            asyncio.create_task(
                self._deepgram_sender_loop("interlocutor", self.pcm_queue_interlocutor)
            )
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

    async def _deepgram_sender_loop(self, source: str, queue: asyncio.Queue):
        """Устанавливает соединение с Deepgram и отправляет данные из очереди"""
        try:
            dg_url = (
                "wss://api.deepgram.com/v1/listen"
                "?encoding=linear16&sample_rate=16000&channels=1"
                "&model=nova-2&language=ru&punctuate=true&smart_format=true"
                "&endpointing=300&diarize=true&interim_results=true"
            )

            async with ws_connect(
                dg_url, extra_headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"}
            ) as ws:
                if source == "me":
                    self.dg_ws_me = ws
                else:
                    self.dg_ws_interlocutor = ws

                logger.info(f"Deepgram connection established for {source}")

                # Задача для отправки данных
                send_task = asyncio.create_task(
                    self._send_data_to_deepgram(source, ws, queue)
                )
                # Задача для приема ответов
                receive_task = asyncio.create_task(
                    self._receive_from_deepgram(source, ws)
                )

                # Ожидаем завершения обеих задач
                await asyncio.gather(send_task, receive_task)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Deepgram connection error for {source}: {e}")
            if self.is_running:
                try:
                    await self.client_ws.send_json(
                        {
                            "type": "error",
                            "message": f"Deepgram error for {source}: {str(e)}",
                        }
                    )
                except:
                    pass

    async def _send_data_to_deepgram(self, source: str, ws, queue: asyncio.Queue):
        """Отправляет PCM данные из очереди в Deepgram"""
        logger.info(f"Starting Deepgram sender for {source}")
        try:
            while self.is_running:
                pcm_data = await queue.get()
                if pcm_data:
                    logger.debug(f"Sending {len(pcm_data)} bytes to Deepgram {source}")
                    await ws.send(pcm_data)
                    queue.task_done()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error sending to Deepgram for {source}: {e}")

    async def _receive_from_deepgram(self, source: str, ws):
        """Принимает ответы от Deepgram"""
        logger.info(f"Starting Deepgram receiver for {source}")
        try:
            async for message in ws:
                await self._handle_deepgram_response(source, message)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error receiving from Deepgram for {source}: {e}")

    async def process_chunk(self, source: int, webm_data: bytes):
        """Обрабатывает входящий чанк с маркировкой источника"""
        if source == 0:  # Микрофон
            await self.ffmpeg_me.write(webm_data)
        elif source == 1:  # Системный звук
            await self.ffmpeg_interlocutor.write(webm_data)

    async def _handle_deepgram_response(self, source: str, message: str):
        """Обрабатывает ответ от Deepgram с улучшенной логикой"""
        try:
            data = json.loads(message)
            msg_type = data.get("type")

            logger.debug(f"Deepgram {source} message type: {msg_type}")

            if msg_type == "Results":
                channel = data.get("channel", {})
                alternatives = channel.get("alternatives", [])

                if alternatives:
                    transcript = alternatives[0].get("transcript", "")
                    is_final = data.get("is_final", False)

                    # Фильтруем пустые транскрипты
                    if not transcript.strip():
                        logger.debug(f"Deepgram {source}: empty transcript, skipping")
                        return

                    logger.info(
                        f"Deepgram {source}: {'FINAL' if is_final else 'interim'} transcript: {transcript}"
                    )

                    # Сохраняем в историю если final
                    if is_final:
                        # Используем реальное время получения ответа
                        current_time = datetime.now()

                        # Создаем элемент диалога с реальным временем
                        dialog_item = {
                            "speaker": source,
                            "text": transcript,
                            "timestamp": current_time,
                            "start_time": current_time,  # Реальное время начала
                            "deepgram_start": data.get("start", 0),
                        }

                        # Объединяем с предыдущей репликой того же говорящего, если пауза маленькая
                        dialog_item = self._merge_with_previous(dialog_item)

                        # Вставляем в хронологическом порядке
                        self._insert_chronologically(dialog_item)

                        # Сохраняем в историю
                        self.transcript_callback(transcript, source)

                    # Отправляем клиенту с реальным временем
                    await self.client_ws.send_json(
                        {
                            "type": "transcript",
                            "text": transcript,
                            "speaker": source,
                            "is_final": is_final,
                            "timestamp": datetime.now().strftime(
                                "%H:%M:%S"
                            ),  # Реальное время HH:MM:SS
                        }
                    )
                else:
                    logger.debug(f"Deepgram {source}: no alternatives in results")

            elif msg_type == "Metadata":
                logger.debug(f"Deepgram {source}: metadata received")
            else:
                logger.debug(f"Deepgram {source}: unknown message type {msg_type}")

        except Exception as e:
            logger.error(f"Error handling Deepgram response for {source}: {e}")

    def _merge_with_previous(self, new_item: dict) -> Optional[dict]:
        """Объединяет новую реплику с предыдущей того же говорящего, если пауза маленькая"""
        if not self.dialog_segments:
            self.last_speaker = new_item["speaker"]
            self.last_segment_end_time = new_item["timestamp"]
            return new_item

        last_item = self.dialog_segments[-1]

        # Проверяем, тот же ли говорящий
        if last_item["speaker"] == new_item["speaker"]:
            # Вычисляем паузу между репликами
            pause_duration = (
                new_item["timestamp"] - self.last_segment_end_time
            ).total_seconds()

            # Если пауза меньше порога, объединяем
            if pause_duration < self.merge_threshold_seconds:
                # Объединяем текст
                merged_text = f"{last_item['text']} {new_item['text']}"

                # Обновляем последний элемент
                last_item["text"] = merged_text
                last_item["timestamp"] = new_item[
                    "timestamp"
                ]  # Обновляем время на время новой реплики

                # Обновляем время окончания
                self.last_segment_end_time = new_item["timestamp"]

                # Удаляем новый элемент (он объединен)
                return None

        # Если не объединили, обновляем последнего говорящего и время
        self.last_speaker = new_item["speaker"]
        self.last_segment_end_time = new_item["timestamp"]
        return new_item

    def _insert_chronologically(self, new_item: Optional[dict]):
        """Вставляет элемент в хронологическом порядке"""
        if new_item is None:  # Элемент был объединен
            return

        new_timestamp = new_item["timestamp"].timestamp()

        for i, item in enumerate(self.dialog_segments):
            if new_timestamp < item["timestamp"].timestamp():
                self.dialog_segments.insert(i, new_item)
                return

        self.dialog_segments.append(new_item)

    async def stop(self):
        """Останавливает процессор немедленно, возвращая уже транскрибированные данные"""
        logger.info("Stopping DialogueProcessor immediately")
        self.is_running = False

        # Немедленно отменяем все активные задачи без ожидания
        if self.active_tasks:
            logger.info(f"Cancelling {len(self.active_tasks)} active tasks...")
            for task in self.active_tasks:
                task.cancel()
            # Не ждем завершения задач - они отменятся асинхронно
            logger.info("Tasks cancelled (not waiting for completion)")

        # Очищаем очереди PCM данных
        logger.info("Clearing PCM queues...")
        while not self.pcm_queue_me.empty():
            try:
                self.pcm_queue_me.get_nowait()
                self.pcm_queue_me.task_done()
            except asyncio.QueueEmpty:
                break

        while not self.pcm_queue_interlocutor.empty():
            try:
                self.pcm_queue_interlocutor.get_nowait()
                self.pcm_queue_interlocutor.task_done()
            except asyncio.QueueEmpty:
                break

        # Закрываем Deepgram соединения (если они еще открыты) без ожидания
        try:
            if self.dg_ws_me:
                self.dg_ws_me.close()
            if self.dg_ws_interlocutor:
                self.dg_ws_interlocutor.close()
        except Exception as e:
            logger.debug(f"Error closing Deepgram connections (expected): {e}")

        # Останавливаем FFmpeg процессы без ожидания
        try:
            self.ffmpeg_me.stop()
            self.ffmpeg_interlocutor.stop()
        except Exception as e:
            logger.error(f"Error stopping FFmpeg: {e}")

        logger.info("DialogueProcessor stopped immediately (non-blocking)")

    def get_dialog_text(self) -> str:
        """Возвращает полный текст диалога с реальным временем"""
        lines = []
        for item in self.dialog_segments:
            speaker_name = "Я" if item["speaker"] == "me" else "Собеседник"
            # Используем реальное время из timestamp
            time_str = item["timestamp"].strftime("%H:%M:%S")
            lines.append(f"[{time_str}] {speaker_name}: {item['text']}")

        return "\n\n".join(lines)
