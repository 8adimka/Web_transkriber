import logging
import sys
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("App")


def get_timestamp_filename():
    """Генерирует имя файла на основе текущего времени"""
    now = datetime.now()
    return f"dialog_{now.strftime('%d.%m.%Y_%H.%M')}.txt"
