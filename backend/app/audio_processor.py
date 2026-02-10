import asyncio
import logging

logger = logging.getLogger("AudioProcessor")


class FFmpegStreamer:
    """
    Запускает FFmpeg в подпроцессе.
    Принимает Opus/WebM чанки в stdin.
    Выдает raw PCM (s16le, 16000Hz, mono) в stdout.
    """

    def __init__(self):
        self.process = None

    async def start(self):
        command = [
            "ffmpeg",
            "-i",
            "pipe:0",  # Чтение из stdin
            "-f",
            "s16le",  # Формат вывода raw PCM
            "-ac",
            "1",  # Моно
            "-ar",
            "16000",  # 16kHz
            "-acodec",
            "pcm_s16le",  # Кодек
            "-hide_banner",
            "-loglevel",
            "error",  # Меньше шума в логах
            "pipe:1",  # Вывод в stdout
        ]

        self.process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        logger.info("FFmpeg subprocess started")

    async def write(self, data: bytes):
        """Пишет сжатые данные (Opus/WebM) в stdin FFmpeg"""
        if self.process and self.process.stdin:
            try:
                self.process.stdin.write(data)
                await self.process.stdin.drain()
            except BrokenPipeError:
                logger.error("FFmpeg stdin pipe broken")

    async def read(self, chunk_size: int) -> bytes:
        """Читает PCM данные из stdout FFmpeg"""
        if self.process and self.process.stdout:
            try:
                # readexactly гарантирует полный чанк для Deepgram,
                # кроме случая EOF
                return await self.process.stdout.readexactly(chunk_size)
            except asyncio.IncompleteReadError as e:
                # Если данных меньше чем просили (конец потока), возвращаем что есть
                return e.partial
            except Exception as e:
                logger.error(f"Error reading from FFmpeg: {e}")
                return b""
        return b""

    async def close_stdin(self):
        """Закрывает ввод, сигнализируя FFmpeg о конце потока"""
        if self.process and self.process.stdin:
            self.process.stdin.close()
            await self.process.stdin.wait_closed()

    async def stop(self):
        """Принудительная остановка"""
        if self.process:
            if self.process.returncode is None:
                try:
                    self.process.terminate()
                    await self.process.wait()
                except ProcessLookupError:
                    pass
            logger.info("FFmpeg subprocess stopped")
