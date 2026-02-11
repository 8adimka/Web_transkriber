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
        self.stderr_task = None

    async def start(self):
        command = [
            "ffmpeg",
            "-i",
            "pipe:0",  # Чтение из stdin
            "-vn",  # Без видео
            "-map",
            "0:a",  # Только аудио дорожка
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
            "-flags",
            "low_delay",
            "-probesize",
            "32",
            "pipe:1",  # Вывод в stdout
        ]

        self.process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        logger.info("FFmpeg subprocess started")

        # Запускаем задачу чтения stderr для отладки
        self.stderr_task = asyncio.create_task(self._read_stderr())

    async def _read_stderr(self):
        """Читает stderr FFmpeg для отладки"""
        if self.process and self.process.stderr:
            try:
                while True:
                    line = await self.process.stderr.readline()
                    if not line:
                        break
                    line_str = line.decode("utf-8", errors="ignore").strip()
                    if line_str:
                        logger.debug(f"FFmpeg stderr: {line_str}")
            except Exception as e:
                logger.error(f"Error reading FFmpeg stderr: {e}")

    async def write(self, data: bytes):
        """Пишет сжатые данные (Opus/WebM) в stdin FFmpeg"""
        if self.process and self.process.stdin:
            try:
                self.process.stdin.write(data)
                await self.process.stdin.drain()
            except BrokenPipeError:
                logger.error("FFmpeg stdin pipe broken")
            except Exception as e:
                logger.error(f"Error writing to FFmpeg: {e}")

    async def read(self, chunk_size: int) -> bytes:
        """Читает PCM данные из stdout FFmpeg"""
        if self.process and self.process.stdout:
            try:
                # Читаем до chunk_size байт, но не блокируемся, если данных меньше
                data = await self.process.stdout.read(chunk_size)
                return data
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
        if self.stderr_task:
            self.stderr_task.cancel()
            try:
                await self.stderr_task
            except asyncio.CancelledError:
                pass

        if self.process:
            if self.process.returncode is None:
                try:
                    self.process.terminate()
                    await self.process.wait()
                except ProcessLookupError:
                    pass
            logger.info("FFmpeg subprocess stopped")
