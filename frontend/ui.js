/* Shared interface language and appearance. Loaded before CSS to avoid a theme flash. */
(function () {
    'use strict';
    const storageKey = 'ui_preferences';
    const translations = {
        'nav.main': ['Main navigation', 'Основная навигация'],
        'saved.pagination': ['Pagination', 'Страницы сохранённых текстов'],
        'profile.accountLabel': ['Account', 'Аккаунт'],
        'profile.avatarInvalid': ['Enter a valid image URL starting with https:// or http://.', 'Введите корректную ссылку на изображение, начинающуюся с https:// или http://.'],
        'auth.googleErrorTitle': ['Google sign-in failed', 'Не удалось войти через Google'],
        'auth.googleErrorHint': ['The sign-in could not be completed. Return to the login page and try again.', 'Не удалось завершить вход. Вернитесь на страницу входа и повторите попытку.'],
        'workspace.captureDenied': ['Audio sharing was not allowed. Check permissions and try again.', 'Доступ к источнику звука не разрешён. Проверьте разрешения и повторите попытку.'],
        'reader.accountChanged': ['Your account changed. Reload this page to continue reading.', 'Аккаунт изменился. Обновите страницу, чтобы продолжить чтение.'],
        'reader.translateUnavailable': ['Translation is unavailable. Please try again later.', 'Перевод временно недоступен. Повторите попытку позже.'],
        'reader.rateLimited': ['Too many translations or the translation limit was reached. Please try again later.', 'Слишком много запросов или достигнут лимит перевода. Повторите попытку позже.'],
        'nav.workspace': ['Workspace', 'Рабочая область'],
        'nav.saved': ['Saved texts', 'Сохранённые тексты'],
        'nav.savedTexts': ['Saved texts', 'Сохранённые тексты'],
        'nav.profile': ['Profile', 'Профиль'],
        'nav.logout': ['Log out', 'Выйти'],
        'nav.login': ['Log in', 'Войти'],
        'nav.register': ['Sign up', 'Регистрация'],
        'common.avatar': ['Avatar', 'Аватар'],
        'common.themeToggle': ['Switch dark mode', 'Переключить тёмную тему'],
        'common.darkTheme': ['Dark mode', 'Тёмная тема'],
        'theme.label': ['Dark mode', 'Тёмная тема'],
        'common.interfaceLanguage': ['Interface language', 'Язык интерфейса'],
        'common.stop': ['Stop', 'Остановить'],
        'common.download': ['Download text', 'Скачать текст'],
        'common.delete': ['Delete', 'Удалить'],
        'common.cancel': ['Cancel', 'Отмена'],
        'common.save': ['Save changes', 'Сохранить изменения'],
        'common.loading': ['Loading…', 'Загрузка…'],
        'common.error': ['Error: {message}', 'Ошибка: {message}'],
        'common.retry': ['Try again', 'Повторить'],
        'common.preferencesLocal': ['Your preference is saved on this device. Account sync is temporarily unavailable.', 'Настройка сохранена на этом устройстве. Синхронизация с аккаунтом временно недоступна.'],
        'workspace.audioSettings': ['Audio settings', 'Настройки аудио'],
        'workspace.languageSettings': ['Languages', 'Языки'],
        'workspace.modes': ['Workspace mode', 'Режим работы'],
        'workspace.result': ['Transcript', 'Текст'],
        'workspace.ready': ['Ready to start', 'Готов к работе'],
        'workspace.placeholderTitle': ['Ready when you are', 'Всё готово к записи'],
        'workspace.placeholder': ['Choose your audio sources, then start recording. Your transcript will appear here.', 'Выберите источники звука и начните запись. Здесь появится текст разговора.'],
        'workspace.translationPlaceholder': ['The complete translation will appear here after you stop.', 'Полный перевод появится здесь после остановки.'],
        'workspace.translationHint': ['Follow the translation in a floating window. The full text appears here when you stop.', 'Следите за переводом в отдельном окне. Полный текст появится здесь после остановки.'],
        'workspace.shareAudio': ['Share tab audio', 'Выбрать звук вкладки'],
        'workspace.shareAudioHint': ['Choose the tab or screen to translate, and enable Share audio in the browser dialog.', 'Выберите вкладку или экран для перевода и включите передачу звука в окне браузера.'],
        'workspace.translationLive': ['Translation is running in the floating window.', 'Перевод идёт в отдельном окне.'],
        'workspace.startRecording': ['Start recording', 'Начать запись'],
        'workspace.startTranslation': ['Start translation', 'Начать перевод'],
        'workspace.initializing': ['Getting ready…', 'Подготовка…'],
        'workspace.recording': ['Recording', 'Идёт запись'],
        'workspace.translating': ['Translating', 'Идёт перевод'],
        'workspace.stopping': ['Finishing and saving…', 'Завершение и сохранение…'],
        'workspace.done': ['Done', 'Готово'],
        'workspace.connectionClosed': ['Connection closed', 'Соединение закрыто'],
        'workspace.microphoneDenied': ['Microphone access is unavailable. Check your browser permissions.', 'Нет доступа к микрофону. Проверьте разрешения браузера.'],
        'workspace.selectSource': ['Select at least one audio source.', 'Выберите хотя бы один источник звука.'],
        'workspace.loginRequired': ['Please log in to start.', 'Для начала работы войдите в аккаунт.'],
        'workspace.noSystemAudio': ['No shared audio. Select a browser tab and enable Share audio.', 'Нет звука. Выберите вкладку браузера и включите «Поделиться аудио».'],
        'workspace.pipUnsupported': ['This browser does not support the floating translation window. Use a browser with Document Picture-in-Picture support.', 'Браузер не поддерживает отдельное окно перевода. Используйте браузер с поддержкой Document Picture-in-Picture.'],
        'workspace.pipUnavailable': ['Could not open the translation window. Allow pop-up windows and try again.', 'Не удалось открыть окно перевода. Разрешите всплывающие окна и повторите попытку.'],
        'workspace.mediaUnsupported': ['Audio capture is not supported by this browser.', 'Браузер не поддерживает захват звука.'],
        'workspace.recordingUnsupported': ['WebM/Opus recording is not supported by this browser.', 'Браузер не поддерживает запись WebM/Opus.'],
        'workspace.sourceUnavailable': ['The selected audio source is unavailable.', 'Выбранный источник звука недоступен.'],
        'workspace.error': ['Could not complete the operation: {message}', 'Не удалось выполнить действие: {message}'],
        'workspace.stopTimeout': ['Finishing took too long. Available text is kept on this page.', 'Завершение заняло слишком много времени. Полученный текст сохранён на странице.'],
        'workspace.saveFailed': ['The text could not be saved to your account. Download a copy from this page.', 'Не удалось сохранить текст в аккаунте. Скачайте копию с этой страницы.'],
        'workspace.sessionExpired': ['Your session has expired. Please log in again.', 'Сессия истекла. Войдите снова.'],
        'workspace.downloadFailed': ['Could not download the text: {message}', 'Не удалось скачать текст: {message}'],
        'workspace.speakerMe': ['Me', 'Я'],
        'workspace.speakerOther': ['Other speaker', 'Собеседник'],
        'workspace.defaultMicrophone': ['Default microphone', 'Микрофон по умолчанию'],
        'workspace.translationSourceNotice': ['Translation uses one audio source. System audio takes priority when both sources are selected.', 'Перевод использует один источник. При выборе обоих используется системный звук.'],
        'workspace.localCopy': ['Download a local copy', 'Скачать локальную копию'],
        'workspace.emptyTranslation': ['No translation was received during this session.', 'За эту сессию текст перевода не получен.'],
        'workspace.providerError': ['The speech or translation service reported an error.', 'Сервис распознавания или перевода сообщил об ошибке.'],
        'audio.microphone': ['Microphone', 'Микрофон'],
        'audio.system': ['System / tab audio', 'Звук системы / вкладки'],
        'audio.device': ['Microphone device', 'Устройство микрофона'],
        'audio.sources': ['Audio sources', 'Источники звука'],
        'language.source': ['Source language', 'Язык оригинала'],
        'language.target': ['Translate to', 'Перевод на'],
        'language.en': ['English', 'Английский'],
        'language.ru': ['Russian', 'Русский'],
        'language.es': ['Spanish', 'Испанский'],
        'language.de': ['German', 'Немецкий'],
        'language.fr': ['French', 'Французский'],
        'mode.transcriber': ['Transcriber', 'Транскрибер'],
        'mode.translator': ['Translator', 'Переводчик'],
        'mode.reader': ['Reader', 'Читалка'],
        'profile.title': ['Profile & preferences', 'Профиль и настройки'],
        'profile.subtitle': ['Your account, audio defaults and workspace preferences.', 'Ваш аккаунт, настройки аудио и рабочей области.'],
        'profile.edit': ['Edit profile', 'Редактировать профиль'],
        'profile.loading': ['Loading your profile…', 'Загрузка профиля…'],
        'profile.joined': ['Joined {date}', 'Дата регистрации: {date}'],
        'profile.audioUsage': ['Audio processed', 'Обработано аудио'],
        'profile.seconds': ['seconds transcribed', 'секунд транскрибировано'],
        'profile.translationUsage': ['Translation', 'Перевод'],
        'profile.characters': ['characters translated', 'символов переведено'],
        'profile.requests': ['API requests', 'Запросы к API'],
        'profile.totalRequests': ['requests in total', 'всего запросов'],
        'profile.period': ['Usage period', 'Период статистики'],
        'profile.currentYear': ['current year', 'текущий год'],
        'profile.appearance': ['Interface', 'Интерфейс'],
        'profile.appearanceHint': ['Language and appearance apply immediately across the app.', 'Язык и оформление сразу применяются ко всему приложению.'],
        'profile.audio': ['Audio defaults', 'Настройки аудио'],
        'profile.enableMic': ['Enable microphone', 'Включить микрофон'],
        'profile.enableTab': ['Enable system / tab audio', 'Включить звук системы / вкладки'],
        'profile.save': ['Save settings', 'Сохранить настройки'],
        'profile.reset': ['Restore defaults', 'Сбросить настройки'],
        'profile.saved': ['Settings saved.', 'Настройки сохранены.'],
        'profile.resetConfirm': ['Restore the default audio settings, English interface and dark mode?', 'Восстановить настройки аудио, английский интерфейс и тёмную тему по умолчанию?'],
        'profile.loadError': ['Could not load your profile.', 'Не удалось загрузить профиль.'],
        'profile.saveError': ['Could not save your settings.', 'Не удалось сохранить настройки.'],
        'profile.account': ['Personal information', 'Личные данные'],
        'profile.fullName': ['Name', 'Имя'],
        'profile.namePlaceholder': ['Your name', 'Ваше имя'],
        'profile.email': ['Email', 'Электронная почта'],
        'profile.emailHint': ['Your email address cannot be changed.', 'Адрес электронной почты изменить нельзя.'],
        'profile.registrationDate': ['Registration date', 'Дата регистрации'],
        'profile.avatarUrl': ['Avatar image URL', 'Ссылка на изображение аватара'],
        'profile.avatarHint': ['Paste an image URL to update your avatar.', 'Вставьте ссылку на изображение для обновления аватара.'],
        'profile.removeAvatar': ['Remove avatar', 'Удалить аватар'],
        'profile.uploadAvatar': ['Upload image', 'Загрузить изображение'],
        'profile.avatarUploadLater': ['Image upload is not available yet. Please use an image URL.', 'Загрузка изображений пока недоступна. Используйте ссылку на изображение.'],
        'profile.removeAvatarConfirm': ['Remove your current avatar?', 'Удалить текущий аватар?'],
        'profile.cancelConfirm': ['Discard changes and return to your profile?', 'Отменить изменения и вернуться в профиль?'],
        'profile.updated': ['Profile saved. Returning to your profile…', 'Профиль сохранён. Возвращаемся на страницу профиля…'],
        'profile.updateError': ['Could not save your profile.', 'Не удалось сохранить профиль.'],
        'password.title': ['Change password', 'Смена пароля'],
        'password.current': ['Current password', 'Текущий пароль'],
        'password.new': ['New password', 'Новый пароль'],
        'password.confirm': ['Confirm new password', 'Подтвердите новый пароль'],
        'password.change': ['Change password', 'Сменить пароль'],
        'password.weak': ['Weak password', 'Слабый пароль'],
        'password.medium': ['Fair password', 'Средний пароль'],
        'password.strong': ['Strong password', 'Сильный пароль'],
        'password.enterCurrent': ['Enter your current password.', 'Введите текущий пароль.'],
        'password.enterNew': ['Enter a new password.', 'Введите новый пароль.'],
        'password.mismatch': ['Passwords do not match.', 'Пароли не совпадают.'],
        'password.minimum': ['Use at least 8 characters for your new password.', 'Новый пароль должен содержать не менее 8 символов.'],
        'password.incorrect': ['The current password is incorrect.', 'Текущий пароль неверен.'],
        'password.changed': ['Your password has been changed.', 'Пароль изменён.'],
        'password.error': ['Could not change your password.', 'Не удалось сменить пароль.'],
        'auth.loginTitle': ['Welcome back', 'С возвращением'],
        'auth.loginHint': ['Log in to continue with your texts.', 'Войдите, чтобы продолжить работу с текстами.'],
        'auth.registerTitle': ['Create an account', 'Создайте аккаунт'],
        'auth.registerHint': ['Keep your transcripts and translations in one place.', 'Храните транскрипции и переводы в одном месте.'],
        'auth.password': ['Password', 'Пароль'],
        'auth.confirmPassword': ['Confirm password', 'Подтвердите пароль'],
        'auth.or': ['or', 'или'],
        'auth.google': ['Continue with Google', 'Продолжить с Google'],
        'auth.noAccount': ['New here? Create an account', 'Нет аккаунта? Зарегистрируйтесь'],
        'auth.hasAccount': ['Already have an account? Log in', 'Уже есть аккаунт? Войдите'],
        "reader.open": ["Open in Reader", "Открыть в читалке"],
        "reader.importTitle": ["A quiet place for your next read", "Место для спокойного чтения"],
        "reader.importHint": ["Paste a text or drop a document here. Click a word or select a phrase to translate it as you read.", "Вставьте текст или перетащите документ. Нажмите на слово или выделите фразу, чтобы получить перевод."],
        "reader.inputLabel": ["Text to read", "Текст для чтения"],
        "reader.inputPlaceholder": ["Paste text or drop a document here…", "Вставьте текст или перетащите документ…"],
        "reader.chooseFile": ["Open document", "Открыть документ"],
        "reader.read": ["Read text", "Читать текст"],
        "reader.formats": ["TXT, FB2, EPUB, DOCX, PDF, Markdown, HTML · up to 10 MB", "TXT, FB2, EPUB, DOCX, PDF, Markdown, HTML · до 10 МБ"],
        "reader.newText": ["New text", "Новый текст"],
        "reader.untitled": ["Untitled text", "Текст без названия"],
        "reader.readingView": ["Reading view", "Область чтения"],
        "reader.bookPage": ["Book page", "Страница текста"],
        "reader.first": ["First page", "Первая страница"],
        "reader.previous": ["Previous page", "Предыдущая страница"],
        "reader.next": ["Next page", "Следующая страница"],
        "reader.last": ["Last page", "Последняя страница"],
        "reader.page": ["Page", "Страница"],
        "reader.pageNumber": ["Page number", "Номер страницы"],
        "reader.pageOf": ["Page {page} of {pages}", "Страница {page} из {pages}"],
        "reader.pagination": ["Reader pages", "Навигация по страницам"],
        "reader.fontDecrease": ["Smaller text", "Уменьшить шрифт"],
        "reader.fontIncrease": ["Larger text", "Увеличить шрифт"],
        "reader.fontSize": ["Text size", "Размер шрифта"],
        "reader.focus": ["Expand reading view", "Развернуть чтение"],
        "reader.exitFocus": ["Exit expanded view", "Свернуть область чтения"],
        "reader.translation": ["Translation", "Перевод"],
        "reader.close": ["Close translation", "Закрыть перевод"],
        "reader.translating": ["Translating…", "Переводим…"],
        "reader.saved": ["Saved", "Сохранено"],
        "reader.saving": ["Saving…", "Сохранение…"],
        "reader.saveFailed": ["Could not save. Your text stays on this page; please try again.", "Не удалось сохранить. Текст остаётся на странице; повторите попытку."],
        "reader.progressSaved": ["Reading position saved", "Место чтения сохранено"],
        "reader.progressSaveFailed": ["Reading position could not sync. It is kept on this device.", "Не удалось синхронизировать место чтения. Оно сохранено на этом устройстве."],
        "reader.loading": ["Opening your text…", "Открываем текст…"],
        "reader.importing": ["Opening your document…", "Открываем документ…"],
        "reader.paginating": ["Preparing pages…", "Подготовка страниц…"],
        "reader.loadError": ["Could not open this text. Please try again.", "Не удалось открыть текст. Повторите попытку."],
        "reader.importError": ["Could not open this document. Check the format and try again.", "Не удалось открыть документ. Проверьте формат и повторите попытку."],
        "reader.translateError": ["Translation is temporarily unavailable. Try again.", "Перевод временно недоступен. Повторите попытку."],
        "reader.translationUnavailable": ["Translation is not configured on the server.", "Перевод не настроен на сервере."],
        "reader.rateLimited": ["Too many translation requests. Please wait a moment.", "Слишком много запросов перевода. Немного подождите."],
        "reader.selectTooLong": ["Select a shorter passage to translate (up to 5,000 characters).", "Выделите фрагмент короче: до 5 000 символов."],
        "reader.emptyText": ["Add some text to begin reading.", "Добавьте текст, чтобы начать чтение."],
        "reader.unsupportedFormat": ["This format is not supported. Choose TXT, FB2, EPUB, DOCX, PDF, Markdown or HTML.", "Этот формат не поддерживается. Выберите TXT, FB2, EPUB, DOCX, PDF, Markdown или HTML."],
        "reader.tooLarge": ["This document is too large. The file limit is 10 MB.", "Документ слишком большой. Максимальный размер файла — 10 МБ."],
        "reader.invalidDocument": ["This document is damaged or cannot be read.", "Документ повреждён или не может быть прочитан."],
        "reader.noText": ["No readable text was found. Scanned PDFs need text recognition first.", "Текст для чтения не найден. PDF-сканам сначала нужно распознавание текста."],
        "reader.encryptedDocument": ["Protected or encrypted documents cannot be opened.", "Защищённые или зашифрованные документы не поддерживаются."],
        "reader.unsupportedLanguage": ["This language pair is not supported for translation.", "Эта языковая пара не поддерживается для перевода."],
        "reader.sourceLanguage": ["Source language", "Язык оригинала"],
        "reader.targetLanguage": ["Translate to", "Перевод на"],
        "reader.resumed": ["Resumed where you left off", "Продолжено с места остановки"],
        "reader.retry": ["Try again", "Повторить"],
        "reader.networkError": ["Could not connect. Your text is kept on this page.", "Нет соединения. Текст остаётся на этой странице."],
        'saved.title': ['Saved texts', 'Сохранённые тексты'],
        'saved.subtitle': ['Your recordings, translations and reading library, all in one place.', 'Ваши записи, переводы и библиотека для чтения в одном месте.'],
        'saved.loading': ['Loading your texts…', 'Загрузка сохранённых текстов…'],
        'saved.empty': ['No saved texts yet', 'Сохранённых текстов пока нет'],
        'saved.emptyHint': ['Record a conversation, translate audio or add a text in Reader.', 'Запишите разговор, запустите перевод или добавьте текст в читалку.'],
        'saved.create': ['Open workspace', 'Открыть рабочую область'],
        'saved.none': ['No texts', 'Нет сохранённых текстов'],
        'saved.count': ['Showing {start}–{end} of {total} texts', 'Показано {start}–{end} из {total} текстов'],
        'saved.page': ['Page {page} of {pages}', 'Страница {page} из {pages}'],
        'saved.previous': ['Previous', 'Назад'],
        'saved.next': ['Next', 'Вперёд'],
        'saved.deleteTitle': ['Delete this text?', 'Удалить этот текст?'],
        'saved.deleteHint': ['This permanently removes the saved text. This action cannot be undone.', 'Сохранённый текст будет удалён. Это действие нельзя отменить.'],
        'saved.loadError': ['Could not load your saved texts.', 'Не удалось загрузить сохранённые тексты.'],
        'saved.downloadError': ['Could not download this text.', 'Не удалось скачать текст.'],
        'saved.deleteError': ['Could not delete this text.', 'Не удалось удалить текст.'],
        'saved.bytes': ['B', 'Б'],
        'saved.kilobytes': ['KB', 'КБ'],
        'saved.megabytes': ['MB', 'МБ']
    };
    const aliases = {
        'Вход...': ['Logging in…', 'Вход…'],
        'Ошибка входа': ['Could not log in', 'Ошибка входа'],
        'Успешный вход! Перенаправление...': ['Logged in. Opening your workspace…', 'Вход выполнен. Открываем рабочую область…'],
        'Пароли не совпадают': ['Passwords do not match', 'Пароли не совпадают'],
        'Регистрация...': ['Creating your account…', 'Создаём аккаунт…'],
        'Ошибка регистрации': ['Could not create your account', 'Ошибка регистрации'],
        'Регистрация успешна! Перенаправление...': ['Account created. Opening your workspace…', 'Аккаунт создан. Открываем рабочую область…'],
        'Ошибка: {message}': ['Error: {message}', 'Ошибка: {message}'],
        'Failed to get Google login URL': ['Could not connect to Google sign-in', 'Не удалось подключиться к входу через Google'],
        'User not found': ['Account not found', 'Аккаунт не найден'],
        'Google client id not configured': ['Google sign-in is not configured', 'Вход через Google не настроен'],
        'Too Many Requests, please wait and try again later.': ['Too many attempts. Please wait and try again.', 'Слишком много попыток. Подождите и повторите.'],
        'Service temporarily unavailable': ['The service is temporarily unavailable', 'Сервис временно недоступен'],
        'Failed to fetch': ['Could not connect. Check your network and try again.', 'Нет соединения. Проверьте сеть и повторите попытку.'],
        'NetworkError when attempting to fetch resource.': ['Could not connect. Check your network and try again.', 'Нет соединения. Проверьте сеть и повторите попытку.'],
        'Incorrect email or password': ['Incorrect email or password', 'Неверная почта или пароль'],
        'Email already registered': ['This email address is already registered', 'Этот адрес электронной почты уже зарегистрирован'],
        'Войти': ['Log in', 'Войти'],
        'Выйти': ['Log out', 'Выйти'],
        'Регистрация': ['Sign up', 'Регистрация']
    };
    Object.assign(translations, aliases);
    // Exact source strings are also accepted while older scripts migrate to semantic keys.
    for (const pair of Object.values(translations)) {
        if (!(pair[1] in translations)) translations[pair[1]] = pair;
        if (!(pair[0] in translations)) translations[pair[0]] = pair;
    }
    let stored = {};
    try { stored = JSON.parse(localStorage.getItem(storageKey) || '{}'); } catch (_) { /* blocked storage */ }
    let language = stored.ui_language === 'ru' ? 'ru' : 'en';
    let theme = stored.theme === 'light' ? 'light' : 'dark';
    let saveQueue = Promise.resolve();
    let preferenceRevision = 0;
    const pending = new Map();

    function t(key, variables = {}) {
        const pair = translations[key];
        let value = pair ? pair[language === 'ru' ? 1 : 0] : key;
        for (const [name, replacement] of Object.entries(variables)) {
            const nested = name === 'message' && translations[replacement];
            const text = nested ? nested[language === 'ru' ? 1 : 0] : String(replacement);
            value = value.split('{' + name + '}').join(text);
        }
        return value;
    }
    function remember() {
        try {
            localStorage.setItem(storageKey, JSON.stringify({ ui_language: language, theme }));
            const cached = JSON.parse(localStorage.getItem('user_settings') || '{}');
            localStorage.setItem('user_settings', JSON.stringify({ ...cached, ui_language: language, theme }));
        } catch (_) { /* interface remains usable when browser storage is blocked */ }
    }
    function translate(root = document) {
        const elements = root.querySelectorAll('[data-i18n], [data-i18n-placeholder], [data-i18n-title], [data-i18n-aria-label], [data-i18n-alt]');
        const list = root.nodeType === 1 ? [root, ...elements] : elements;
        for (const element of list) {
            for (const suffix of ['', '-placeholder', '-title', '-aria-label', '-alt']) {
                const key = element.getAttribute('data-i18n' + suffix);
                if (!key) continue;
                if (!suffix) element.textContent = t(key);
                else element.setAttribute(suffix.slice(1), t(key));
            }
        }
    }
    function render() {
        document.documentElement.lang = language;
        document.documentElement.dataset.theme = theme;
        translate();
        document.querySelectorAll('[data-theme-toggle]').forEach(input => { input.checked = theme === 'dark'; });
        document.querySelectorAll('[data-ui-language]').forEach(input => { input.value = language; });
    }
    function announce() {
        render();
        document.dispatchEvent(new CustomEvent('ui:change', { bubbles: true, detail: { language, theme } }));
    }
    function showSyncNotice() {
        let notice = document.getElementById('uiSyncNotice');
        if (!notice && document.body) {
            notice = document.createElement('div');
            notice.id = 'uiSyncNotice';
            notice.className = 'ui-notice';
            notice.setAttribute('role', 'status');
            notice.dataset.i18n = 'common.preferencesLocal';
            document.body.appendChild(notice);
        }
        if (notice) { notice.textContent = t('common.preferencesLocal'); notice.hidden = false; }
    }
    function persist(patch) {
        let token = null;
        try { token = localStorage.getItem('access_token'); } catch (_) { /* blocked storage */ }
        if (!token) return Promise.resolve(true);
        Object.keys(patch).forEach(key => pending.set(key, (pending.get(key) || 0) + 1));
        saveQueue = saveQueue.catch(() => {}).then(async () => {
            try {
                const options = { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) };
                const response = window.auth?.authFetch
                    ? await window.auth.authFetch('/user/settings', options)
                    : await fetch('/user/settings', { ...options, headers: { ...options.headers, Authorization: 'Bearer ' + token } });
                if (!response?.ok) throw new Error('Preference sync failed');
                const notice = document.getElementById('uiSyncNotice');
                if (notice) notice.hidden = true;
                return true;
            } catch (_) {
                showSyncNotice();
                return false;
            } finally {
                Object.keys(patch).forEach(key => {
                    const count = pending.get(key) - 1;
                    if (count > 0) pending.set(key, count); else pending.delete(key);
                });
            }
        });
        return saveQueue;
    }
    function setLanguage(value, save = true) {
        preferenceRevision++;
        language = value === 'ru' ? 'ru' : 'en';
        remember();
        announce();
        return save ? persist({ ui_language: language }) : Promise.resolve(true);
    }
    function setTheme(value, save = true) {
        preferenceRevision++;
        theme = value === 'light' ? 'light' : 'dark';
        remember();
        announce();
        return save ? persist({ theme }) : Promise.resolve(true);
    }
    function applyPreferences(settings = {}, expectedRevision) {
        // A response issued before a local choice must not undo it, even after PUT completed.
        const current = expectedRevision === undefined || expectedRevision === preferenceRevision;
        if (current && !pending.has('ui_language') && ['en', 'ru'].includes(settings.ui_language)) language = settings.ui_language;
        if (current && !pending.has('theme') && ['dark', 'light'].includes(settings.theme)) theme = settings.theme;
        remember();
        announce();
    }
    window.UI = {
        t, translate, setLanguage, setTheme, applyPreferences,
        get preferenceRevision() { return preferenceRevision; },
        get language() { return language; },
        get theme() { return theme; },
        get locale() { return language === 'ru' ? 'ru-RU' : 'en-US'; }
    };
    document.documentElement.lang = language;
    document.documentElement.dataset.theme = theme;
    document.addEventListener('DOMContentLoaded', () => {
        render();
        document.querySelectorAll('[data-theme-toggle]').forEach(input => {
            input.addEventListener('change', () => setTheme(input.checked ? 'dark' : 'light'));
        });
        document.querySelectorAll('[data-ui-language]').forEach(input => {
            input.addEventListener('change', () => setLanguage(input.value));
        });
    });
    window.addEventListener('storage', event => {
        if (event.key !== storageKey) return;
        try { applyPreferences(JSON.parse(event.newValue || '{}')); } catch (_) { /* malformed storage */ }
    });
})();
