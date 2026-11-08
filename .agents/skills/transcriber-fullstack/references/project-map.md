# Карта проекта и действующих контрактов

Обновлено: 2026-11-07, HEAD `2dae364` плюс локальные изменения интерфейса, предпочтений, сохранения перевода и Reader. Пути ниже — от корня репозитория; символы помогают проверить факт после изменения строк. Это навигация по коду, не замена чтению реализации.

## Устройство

| Область | Точка входа и ответственность |
| --- | --- |
| Reader | `frontend/reader.js`, `transcriber/app/reader_routes.py`, `document_import.py`: импорт, чтение, перевод выделения и позиция |
| Страница записи | `frontend/index.html`, `auth.js`, `app.js`: выбор источников, запись, перевод, PiP, скачивание |
| Вход и регистрация | `frontend/login.html`, `register.html`, `auth.js` |
| Профиль и настройки | `frontend/profile.html`, `profile.js`, `edit_profile.html`, `edit_profile.js` |
| История | `frontend/transcriptions.html`, `transcriptions.js`: список, пагинация, скачать/удалить |
| Общий UI | `frontend/ui.js`, `styles.css`: EN/RU, тема, синхронизация предпочтений; точные DOM ID и порядок обычных скриптов являются зависимостями |
| Auth API | `backend/services/auth/app/main.py`; роутеры `app/routers/{auth,user_profile,token_stats}.py` |
| Transcriber API | `backend/services/transcriber/app/main.py`, `ws_routes.py`, `session_manager.py` |
| Аудио | `transcriber/app/audio_processor.py`: `FFmpegStreamer`, `UniversalProcessor` |
| Перевод | `transcriber/app/translation_service.py::TranslationService` — DeepL HTTP |
| Общие компоненты | `backend/shared/{redis,rate_limiter,token_tracker,user_settings}/` |
| Внешний вход | `nginx/nginx.conf`, `docker-compose.yml` |

Фронтенд не использует React, npm, сборщик или JS-модули. Pytest/CI не настроены. Новые регрессии используют unittest и встроенный node:test; см. `verification.md`. `frontend/test_api.html` — ручная диагностика.

В Compose шесть сервисов: auth, transcriber, frontend (Nginx), postgres_auth, postgres_transcriber, redis_container. Docker auth — Python 3.12; transcriber — Python 3.11 и FFmpeg. Точные версии библиотек находятся в отдельных `requirements.txt`; они различаются.

## Хранилища и запуск

- Auth PostgreSQL: `auth/app/models.py::{User,UserSettings,TokenUsage,TokenEvent}`. `User` хранит локальный refresh token; не предполагай наличие отдельной рабочей таблицы refresh tokens по названию старой миграции.
- Auth миграции: `auth/app/alembic/versions/0001…0005`; `0005_ui_preferences` добавляет `ui_language` (`en`/`ru`) и `theme` (`dark`/`light`) с default `en`/`dark`. `auth/entrypoint.sh` ждёт БД, выполняет `alembic upgrade head` и запускает Uvicorn.
- Transcriber PostgreSQL: `transcriber/app/database.py::Transcription`, `init_db` вызывает `Base.metadata.create_all`. CRUD в `app/crud.py`.
- Redis: лимиты HTTP/WS, текущая статистика использования, события провайдеров, кэш настроек. Долговременная статистика — auth PostgreSQL; `shared/token_tracker/sync_worker.py::TokenSyncWorker` пытается синхронизировать её фоном.
- `Session.save_to_db` сохраняет непустой финальный текст обоих режимов — `transcription` и `translation` — в прежнюю таблицу. Финальный перевод хранится в `Session.translation_log`, SQLAlchemy выполняется через `asyncio.to_thread`. Остановка сначала завершает FFmpeg/Deepgram, затем сохраняет и отправляет `done`.
- `TokenUsage` считает Deepgram в секундах и DeepL в символах. Название «токены» не означает токены языковой модели или точный счёт провайдера.
- Compose монтирует auth app и shared. Transcriber app копируется в образ, его правки требуют пересборки. Nginx получает frontend через volume.

## REST и прокси

Основной внешний адрес разработки — `https://localhost`. Compose публикует auth как `localhost:8000`, transcriber как `localhost:8001`; оба приложения внутри контейнеров слушают 8000. Не путай прямые порты с HTTPS-прокси.

| Внешний путь Nginx | Backend |
| --- | --- |
| `/auth/…`, `/api/auth/…` | auth `/auth/…` |
| `/user/…`, `/token-stats/…` | одноимённые пути auth |
| `/auth/health` | auth `/health` |
| `/health` | transcriber `/health` |
| `/ws/…` | transcriber, WebSocket Upgrade |
| `/transcriptions`, `/transcriptions/…` | одноимённые пути transcriber |
| `/download/…` | старый download transcriber |
| `/api/transcriber/…` | transcriber, префикс `/api/transcriber/` удаляется |

Неизвестные пути могут попасть в статический fallback `/index.html`. У `/rate-limiter/*` нет собственного внешнего location, хотя router подключён к обоим приложениям. HTTP перенаправляется на HTTPS localhost.

Auth router (`auth/app/routers/auth.py`):

| Метод/путь backend | Вход и результат |
| --- | --- |
| `POST /auth/register/` | JSON `email`, `password`; схема `UserCreate` сейчас не содержит присылаемое UI `full_name` |
| `POST /auth/token/` | OAuth2 form: `username`, `password`; JSON-вход не эквивалентен |
| `POST /auth/refresh/` | JSON `refresh_token` |
| `GET /auth/google/login` | JSON `login_url`, затем переход браузера |
| `GET /auth/callback/google` | callback OAuth; проверь redirect/state и обработку ошибок в реализации |
| `POST /auth/google/refresh-info` | обновление информации Google-пользователя |

Регистрация, вход и refresh возвращают `access_token`, `refresh_token`, `token_type`, `id`, `email`, `full_name`, `picture_url`, `auth_provider`. Access JWT — RS256, `sub` строкой содержит ID. `auth/app/dependencies.py` подписывает/проверяет токены, `transcriber/app/dependencies.py` проверяет их общим публичным ключом.

Профиль и статистика требуют `Authorization: Bearer …`:

- `GET/PUT /user/profile`, `GET/PUT /user/settings`, `POST /user/change-password`.
- `GET /user/stats/summary` возвращает `profile: {user, settings}` и `token_stats`; это основной запрос страниц профиля.
- `GET /user/settings` возвращает объект с `settings`. Поля настроек: `microphone_enabled`, `tab_audio_enabled`, `original_language`, `translation_language`, `avatar_url`, `ui_language`, `theme`. Частичные PUT не сбрасывают пропущенные поля; неполный старый Redis-кэш восполняется из PostgreSQL.
- `GET /user/settings/redis/sync` имеет действие синхронизации; не считай любой GET операцией без побочного эффекта.
- `GET /token-stats/{current,history,summary,periods,events}` — см. `token_stats.py` для query/ответов.

Transcriber сейчас использует query `token`, в том числе для REST:

- `GET /transcriptions?skip=0&limit=10&token=…` → `transcriptions`, `total`, `skip`, `limit`. Поля записи: `id`, `user_id`, `filename`, `content`, `orig_language`, `translate_to`, `file_size`, `created_at`.
- `GET /transcriptions/{id}/download?token=…` → текст, имя через `Content-Disposition`.
- `DELETE /transcriptions/{id}?token=…` → `success`, `message`.
- Старый `GET /download/{filename}?token=…` ещё существует; проверка владельца отличается от нового пути.

`frontend/auth.js` хранит `access_token`, `refresh_token`, `user_info`, `user_settings` в localStorage и предоставляет `window.auth`. `authFetch` умеет refresh и объединяет конкурентные refresh-запросы. Профиль использует его; история и скачивание пересобирают query token после refresh. `ui.js::UI` хранит локальные предпочтения, переводит `data-i18n`, отправляет частичные PUT и защищает новый выбор `preferenceRevision` от запоздалой hydration. Событие `ui:change` обновляет динамические состояния.

## Аудиоконтракт

Клиент: `frontend/app.js::{setupWebSocket,setupMicStream,setupSystemStream,stopRecording,handleServerMessage}`. Сервер: `ws_routes.py::websocket_endpoint`, `session_manager.py::{handle_audio_chunk,stop_session}`, `audio_processor.py::UniversalProcessor`.

1. Подключение: `ws[s]://<current-host>/ws/stream?token=…`; сервер проверяет JWT и лимит до accept.
2. JSON начала транскрибации: `{"type":"start","language":"RU","target_lang":"EN","sample_rate":48000}`. Значение sample_rate в примере условное, клиент берёт его из AudioContext; сервер start-ветки его сейчас не использует.
3. JSON начала перевода: `{"type":"start_translation","source_lang":"EN","target_lang":"RU","sample_rate":48000}`.
4. Binary: **один байт источника + WebM/Opus chunk**. `0x00` — микрофон, `0x01` — системный звук/вкладка. Два MediaRecorder, интервал 450 мс. Это не raw PCM и не объединённый browser-side поток.
5. FFmpeg преобразует каждый поток в mono `s16le`, 16 kHz. Deepgram получает `linear16`, 16 kHz, 1 канал; endpoint/model/параметры см. `_deepgram_loop`. Транскрибация использует два источника, перевод — один поток.
6. JSON остановки: `{"type":"stop"}`. Клиент ждёт финальных recorder stop/dataavailable и sendQueue, затем посылает stop и ждёт `done` до 60 сек; `completeSession` закрывает WS и media/PiP. Сервер дренирует PCM и завершает Deepgram через CloseStream; при неполном завершении сообщает `incomplete`.

| Сообщение сервера | Поля |
| --- | --- |
| `status`, `error` | `message` (`status` сейчас не отображается клиентом) |
| `transcript` | `text`, `speaker`, `is_final`, `timestamp`; `speaker="me"` — микрофон |
| `translation` | `original`, `translated`, `is_final`, `timestamp` |
| `done` | `message`, `saved`, `empty`, `incomplete`; при сохранении `transcription_id` строкой, `download_url` без токена |

Клиент использует сохранение по ID. При `save_failed` доступна локальная текстовая копия финальных сегментов; исходный legacy REST `/download/{filename}` ещё существует. Время в текущих сообщениях — строка `HH:MM:SS`, не обязательно длительность в секундах.

Rate limiter считает и JSON, и binary сообщения. Промежуточный текст (`is_final=false`) заменяется, финальный добавляется; проверь отсутствие дублей при изменении накопления. Потоковый перевод использует Deepgram + DeepL; без ключа/при ошибке DeepL текущая реализация может вернуть оригинальный текст.

PiP основан на Document Picture-in-Picture: DOM `pipContainer` переносится между окнами, `pagehide` вызывает остановку. UI исходных языков: RU/EN/ES, целевых: RU/EN; это не доказательство поддержки всех сочетаний провайдерами.

## Режимы и внешний вид

Главная использует вкладки Transcriber/Translator/Reader (`app.js::selectMode`), выбранная вкладка независима от активной записи. Во время одной сессии старт другой запрещён. Результаты двух режимов хранятся отдельно в `modeViews`, `resultSection` перемещается между панелями. Reader реализован: вставка/импорт документов, адаптивная постраничная верстка, перевод слова/выделения, автосохранение и восстановление позиции.

В Translator основной результат скрыт до завершения, весь финальный текст накапливается независимо от шести видимых фраз PiP. Для системного звука после открытия PiP пользователь нажимает Share tab audio внутри окна: PiP и getDisplayMedia требуют отдельных действий пользователя. При отсутствии Document PiP используется обычное всплывающее окно. Закрытие окна останавливает сессию.

Предпочтения: `ui.js` загружается до CSS, по умолчанию `en`/`dark`; переключатель темы в header и профиле, язык интерфейса только в настройках Profile. Страницы профиля и истории изолируют JS через IIFE, вывод текстов использует DOM/textContent. Раздел истории отображается как Saved texts / Сохранённые тексты; URL `transcriptions.html` сохранён.

## Reader API и документы

Новые Bearer-маршруты `reader_routes.py` доступны через Nginx `/api/transcriber/reader/` (префикс переписывается в `/reader/`).

- `POST /documents`: JSON `title`, `content`, `source_lang`, `target_lang`, `client_id` UUID. Текст создаётся в прежней `Transcription`; UUID исключает дубликаты при повторе автосохранения.
- `POST /import`: бинарное тело, URL-encoded заголовок `X-File-Name`, `Idempotency-Key` UUID, query `source_lang`/`target_lang`. `document_import.extract_document` извлекает только текст в памяти из TXT/TEXT, FB2, EPUB (spine), DOCX, PDF с текстовым слоем, MD/Markdown и HTML/HTM. Лимиты10MiB файла,5млн символов,40MiB распакованного архива. OCR/DRM/MOBI/AZW/RTF/DjVu не реализованы.
- `GET /documents/{id}`: любой сохранённый текст текущего пользователя, включая старые транскрипции/переводы. Ответ `id,title,content,source_lang,target_lang,position,page,progress_updated_at_ms,created_at`.
- `PATCH /documents/{id}/progress`: `position` в UTF-16 code units, `page`, `updated_at_ms`; атомарная проверка timestamp не позволяет старому запросу вернуть прежнюю позицию.
- `POST /translate`: JSON `text` до5000 символов, `source_lang`, `target_lang`; ответ `translated`. Только выбранная фраза отправляется DeepL, весь документ остаётся локально/в своей БД. Без ключа/при ошибке — явная ошибка, одинаковые языки возвращают исходный текст.

`database.ReaderState` — новая таблица `reader_states` с FK/cascade к существующему тексту, создаётся idempotent `create_all`; исходная таблица не alter. Все новые пути проверяют владельца. Список истории поддерживает `preview_chars=300`, выполняемый SQL substring, и COUNT без полной загрузки книг.

`reader.js` измеряет страницу при актуальном шрифте/ширине/высоте, сохраняет непрерывные границы UTF-16 и делает пагинацию с уступкой RAF. При reflow сохраняется текстовый anchor. В DOM находятся слова только текущей страницы; импортированный HTML никогда не исполняется. Popup имеет обычный выделяемый текст; selection внутри него не порождает новый перевод. Устаревшие запросы отменяются.

Pending импорт/вставка хранится в IndexedDB по аккаунту; постоянные ошибки413/415/422 удаляют ошибочный draft, временные ошибки допускают повтор тем жеUUID. Позиция немедленно сохраняется локально, debounce/PATCH и keepalive при закрытии дополняют серверное хранение. Аккаунт фиксируется при загрузке Reader; смена аккаунта не пересылает старый текст под новой авторизацией.

Вход из библиотеки: `index.html?reader=<id>`, новый Reader: `?mode=reader`. Основные UI: readerInput/File/Book/Page, readerPageNumber/Total, readerFirst/Previous/Next/Last, readerFocus. Режим фокуса скрывает лишние панели; Stop активной аудиосессии остаётся доступным.
