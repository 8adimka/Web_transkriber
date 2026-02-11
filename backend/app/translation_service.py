import logging
import os
from typing import Dict, Optional

import httpx

logger = logging.getLogger("TranslationService")

DEEPL_API_KEY = os.getenv("DEEPL_API_KEY")
DEEPL_API_URL = "https://api-free.deepl.com/v2/translate"


class TranslationService:
    """Сервис для перевода текста через DeepL API"""

    def __init__(self):
        self.api_key = DEEPL_API_KEY
        self.client: Optional[httpx.AsyncClient] = None
        self.translation_cache: Dict[str, str] = {}
        self.request_timeout = 5.0  # секунд

    async def start(self):
        """Инициализирует HTTP клиент"""
        if not self.api_key:
            logger.warning("DeepL API key not set. Translation will be disabled.")
            return

        self.client = httpx.AsyncClient(
            timeout=self.request_timeout,
            headers={
                "Authorization": f"DeepL-Auth-Key {self.api_key}",
                "User-Agent": "WebTranscriber/1.0",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        logger.info("TranslationService started")

    async def stop(self):
        """Останавливает HTTP клиент"""
        if self.client:
            await self.client.aclose()
            self.client = None
            logger.info("TranslationService stopped")

    async def translate(
        self,
        text: str,
        target_lang: str = "RU",
        source_lang: Optional[str] = None,
    ) -> str:
        """
        Переводит текст через DeepL API.

        Args:
            text: Текст для перевода
            target_lang: Целевой язык (по умолчанию "RU")
            source_lang: Исходный язык (опционально, автоопределение если None)

        Returns:
            Переведенный текст или оригинал в случае ошибки
        """
        if not text or not text.strip():
            return ""

        # Проверяем кэш
        cache_key = f"{source_lang or 'auto'}:{target_lang}:{text}"
        if cache_key in self.translation_cache:
            logger.debug(f"Cache hit for: {text[:50]}...")
            return self.translation_cache[cache_key]

        # Если API ключ не установлен, возвращаем оригинал
        if not self.api_key or not self.client:
            logger.warning("DeepL API not available, returning original text")
            return text

        # Подготавливаем данные для запроса
        data = {
            "text": text,
            "target_lang": target_lang,
        }
        if source_lang:
            data["source_lang"] = source_lang

        try:
            logger.debug(f"Translating: {text[:50]}...")
            response = await self.client.post(DEEPL_API_URL, data=data)
            response.raise_for_status()

            result = response.json()
            if "translations" in result and len(result["translations"]) > 0:
                translated = result["translations"][0]["text"]
                # Сохраняем в кэш
                self.translation_cache[cache_key] = translated
                logger.debug(f"Translated: {text[:50]}... -> {translated[:50]}...")
                return translated
            else:
                logger.error(f"Unexpected DeepL response: {result}")
                return text

        except httpx.TimeoutException:
            logger.warning(f"DeepL API timeout for: {text[:50]}...")
            return text
        except httpx.HTTPStatusError as e:
            logger.error(
                f"DeepL API HTTP error: {e.response.status_code} - {e.response.text}"
            )
            return text
        except Exception as e:
            logger.error(f"DeepL API error: {e}")
            return text

    def clear_cache(self):
        """Очищает кэш переводов"""
        self.translation_cache.clear()
        logger.debug("Translation cache cleared")


# Глобальный экземпляр сервиса
translation_service = TranslationService()
