import logging
import os
from typing import Dict, Optional

import httpx

logger = logging.getLogger("TranslationService")

DEEPL_API_KEY = os.getenv("DEEPL_API_KEY")
DEEPL_API_URL = "https://api-free.deepl.com/v2/translate"


class TranslationService:
    """
    Сервис перевода через DeepL.
    Использует кэширование для ускорения Real-time перевода.
    """

    def __init__(self):
        self.api_key = DEEPL_API_KEY
        self.client: Optional[httpx.AsyncClient] = None
        # Кэш переводов: "Original text" -> "Translated text"
        # Это критически важно для interim результатов, чтобы не дублировать запросы
        self.cache: Dict[str, str] = {}

    async def start(self):
        self.client = httpx.AsyncClient(
            timeout=5.0,
            headers={
                "Authorization": f"DeepL-Auth-Key {self.api_key}",
                "User-Agent": "WebTranscriber/2.0",
            },
        )
        if self.api_key:
            logger.info("TranslationService: DeepL ready")
        else:
            logger.warning(
                "TranslationService: DeepL key missing! Translations will fail."
            )

    async def stop(self):
        if self.client:
            await self.client.aclose()

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        """
        Переводит текст. Если текст уже был переведен ранее (например, в interim),
        возвращает результат из кэша мгновенно.
        """
        if not text or not text.strip():
            return ""

        # Если ключа нет, возвращаем оригинал
        if not self.api_key or not self.client:
            return text

        # Нормализация ключа кэша
        text_key = text.strip()
        cache_key = f"{source_lang}:{target_lang}:{text_key}"

        # 1. Проверка кэша (Оптимизация скорости из RealTimeSubtitles)
        if cache_key in self.cache:
            return self.cache[cache_key]

        try:
            # 2. Запрос к DeepL
            data = {
                "text": text_key,
                "target_lang": target_lang.upper(),
                "source_lang": source_lang.upper()
                if source_lang and source_lang != "auto"
                else None,
            }
            # Удаляем пустые ключи
            data = {k: v for k, v in data.items() if v is not None}

            response = await self.client.post(DEEPL_API_URL, data=data)
            response.raise_for_status()

            result_json = response.json()
            if "translations" in result_json:
                translated = result_json["translations"][0]["text"]
                # Сохраняем в кэш
                self.cache[cache_key] = translated
                return translated

            return text

        except Exception as e:
            logger.error(f"DeepL API error: {e}")
            return text


# Глобальный экземпляр
translation_service = TranslationService()
