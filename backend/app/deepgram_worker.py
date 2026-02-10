import asyncio
import json
import logging
import os

from websockets.client import connect as ws_connect

from .audio_processor import FFmpegStreamer

logger = logging.getLogger("DeepgramWorker")

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
# Размер чанка для отправки в Deepgram (байты PCM)
# 3200 bytes = 100ms @ 16kHz 16bit.
# 48000 bytes = 1.5 sec.
# Рекомендация Deepgram ~20-250ms, но WebSockets держат и больше.
# Возьмем из env или дефолт 3200 * 5 (100ms * 5 = 500ms)
DG_CHUNK_SIZE = int(os.getenv("DEEPGRAM_CHUNK_SIZE", 3200 * 5))


class DeepgramWorker:
    def __init__(self, input_queue: asyncio.Queue, client_ws, transcript_callback):
        self.input_queue = input_queue
        self.client_ws = client_ws
        self.transcript_callback = transcript_callback  # Функция для сохранения истории
        self.is_running = True
        self.ffmpeg = FFmpegStreamer()

        # Diarize=true помогает различить спикеров, если они не говорят одновременно
        self.dg_url = (
            "wss://api.deepgram.com/v1/listen"
            "?encoding=linear16&sample_rate=16000&channels=1"
            "&model=nova-2&language=ru&punctuate=true&smart_format=true"
            "&endpointing=300&diarize=true&interim_results=true"
        )

    async def run(self):
        if not DEEPGRAM_API_KEY:
            logger.error("DEEPGRAM_API_KEY is missing")
            await self.client_ws.send_json(
                {"type": "error", "message": "Server config error"}
            )
            return

        await self.ffmpeg.start()

        headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}

        try:
            async with ws_connect(self.dg_url, extra_headers=headers) as dg_ws:
                logger.info("Connected to Deepgram")

                # Запускаем параллельные задачи
                send_task = asyncio.create_task(self._process_audio_pipeline(dg_ws))
                recv_task = asyncio.create_task(self._handle_deepgram_responses(dg_ws))

                await asyncio.gather(send_task, recv_task)

        except Exception as e:
            logger.error(f"Deepgram connection error: {e}")
            if self.is_running:
                try:
                    await self.client_ws.send_json({"type": "error", "message": str(e)})
                except:
                    pass
        finally:
            await self.ffmpeg.stop()

    async def _process_audio_pipeline(self, dg_ws):
        """
        1. Читает WebM из очереди (от клиента).
        2. Пишет в FFmpeg stdin.
        3. Читает PCM из FFmpeg stdout.
        4. Шлет в Deepgram.
        """

        # Задача на чтение очереди и запись в FFmpeg
        async def feed_ffmpeg():
            while self.is_running:
                try:
                    # Ждем данные 1 секунду, чтобы проверить флаг is_running
                    chunk = await asyncio.wait_for(self.input_queue.get(), timeout=1.0)
                    if chunk is None:  # Sentinel value for EOF
                        break
                    await self.ffmpeg.write(chunk)
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Feed FFmpeg error: {e}")
                    break
            await self.ffmpeg.close_stdin()

        # Задача на чтение FFmpeg и отправку в Deepgram
        async def feed_deepgram():
            while self.is_running:
                # Читаем фиксированный размер чанка PCM
                pcm_data = await self.ffmpeg.read(DG_CHUNK_SIZE)
                if not pcm_data:
                    # Если данных нет, возможно FFmpeg закрылся или еще не декодировал
                    if not self.input_queue.empty() or self.is_running:
                        await asyncio.sleep(0.01)
                        continue
                    else:
                        break

                await dg_ws.send(pcm_data)

            # Отправляем закрытие потока Deepgram
            await dg_ws.send(json.dumps({"type": "CloseStream"}))

        await asyncio.gather(feed_ffmpeg(), feed_deepgram())

    async def _handle_deepgram_responses(self, dg_ws):
        """Получает ответы от Deepgram и пересылает клиенту"""
        try:
            async for message in dg_ws:
                data = json.loads(message)

                msg_type = data.get("type")

                if msg_type == "Results":
                    channel = data.get("channel", {})
                    alternatives = channel.get("alternatives", [])

                    if alternatives:
                        transcript = alternatives[0].get("transcript", "")
                        is_final = data.get("is_final", False)

                        if transcript.strip():
                            # Сохраняем в историю если final
                            if is_final:
                                self.transcript_callback(transcript)

                            # Шлем клиенту
                            await self.client_ws.send_json(
                                {
                                    "type": "transcript",
                                    "text": transcript,
                                    "is_final": is_final,
                                    "timestamp": data.get("start", 0),
                                }
                            )

                elif msg_type == "Metadata":
                    # Стрим завершен со стороны Deepgram
                    break

        except Exception as e:
            logger.error(f"Error receiving from Deepgram: {e}")

    def stop(self):
        self.is_running = False
