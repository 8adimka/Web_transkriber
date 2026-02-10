import logging
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("WebTranscriber")


def get_timestamp_filename():
    """Генерирует имя файла на основе текущего времени."""
    return f"dialog_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"
