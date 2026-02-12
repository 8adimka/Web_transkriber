import asyncio
import logging

logger = logging.getLogger("AudioProcessor")


class FFmpegStreamer:
    """
    Запускает FFmpeg и читает RAW PCM данные.
    Максимально упрощенная и надежная версия.
    """

    def __init__(self):
        self.process = None

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
        logger.info("FFmpeg streamer started")

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
        if self.process:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
                self.process.terminate()
                await self.process.wait()
            except Exception:
                pass
        logger.info("FFmpeg streamer stopped")
