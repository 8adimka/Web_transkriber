let ws = null;
let micRecorder = null;
let systemRecorder = null;
let audioContext = null;
let micStream = null;
let systemStream = null;

const statusEl = document.getElementById('statusBar');
const transcriptBox = document.getElementById('transcriptBox');
const btnStart = document.getElementById('btnStart');
const btnStartTranslation = document.getElementById('btnStartTranslation');
const btnStop = document.getElementById('btnStop');
const micSelect = document.getElementById('micSelect');
const downloadSection = document.getElementById('downloadSection');
const downloadLink = document.getElementById('downloadLink');
const sourceLang = document.getElementById('sourceLang');
const targetLang = document.getElementById('targetLang');
const useMicCheckbox = document.getElementById('useMic');
const useSystemCheckbox = document.getElementById('useSystem');

// Элементы аутентификации
const authSection = document.getElementById('authSection');
const userInfo = document.getElementById('userInfo');
const userName = document.getElementById('userName');
const logoutBtn = document.getElementById('logoutBtn');
const loginPrompt = document.getElementById('loginPrompt');

// Элементы PiP (будут привязаны при открытии окна)
const pipContainer = document.getElementById('pipContainer');
const pipFinalPhrases = document.getElementById('pipFinalPhrases');
const pipInterimPhrase = document.getElementById('pipInterimPhrase');
let pipWindow = null;

// Режим работы
let currentMode = 'transcription';
let currentInterim = null;

// Инициализация аутентификации
function initAuth() {
    const token = localStorage.getItem('access_token');
    const userInfoStr = localStorage.getItem('user_info');

    if (token && userInfoStr) {
        try {
            const user = JSON.parse(userInfoStr);
            userName.textContent = user.full_name || user.email;
            userInfo.style.display = 'block';
            loginPrompt.style.display = 'none';
        } catch (e) {
            console.error('Failed to parse user info', e);
            logout();
        }
    } else {
        userInfo.style.display = 'none';
        loginPrompt.style.display = 'block';
        // Если пользователь не авторизован и находится на главной странице,
        // перенаправляем на страницу входа
        if (window.location.pathname.endsWith('index.html') || window.location.pathname === '/') {
            window.location.href = 'login.html';
        }
    }
}

// Выход
if (logoutBtn) {
    logoutBtn.addEventListener('click', () => {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('user_info');
        window.location.reload();
    });
}

// Проверка аутентификации перед запуском
function checkAuth() {
    const token = localStorage.getItem('access_token');
    if (!token) {
        alert('Для использования транскрибера необходимо войти в систему.');
        window.location.href = 'login.html';
        return false;
    }
    return true;
}

// Загрузка устройств
async function loadDevices() {
    try {
        await navigator.mediaDevices.getUserMedia({ audio: true });
        const devices = await navigator.mediaDevices.enumerateDevices();
        const mics = devices.filter(d => d.kind === 'audioinput');
        micSelect.innerHTML = mics.map(m => `<option value="${m.deviceId}">${m.label || 'Microphone ' + m.deviceId}</option>`).join('');
    } catch (e) {
        console.error("Access denied", e);
        statusEl.textContent = "Ошибка доступа к микрофонам";
    }
}
loadDevices();
initAuth();

// Управление UI состоянием
function setRunningUi(isRunning) {
    btnStart.style.display = isRunning ? 'none' : 'inline-block';
    btnStartTranslation.style.display = isRunning ? 'none' : 'inline-block';
    btnStop.style.display = isRunning ? 'inline-block' : 'none';

    micSelect.disabled = isRunning;
    sourceLang.disabled = isRunning;
    targetLang.disabled = isRunning;
}

btnStart.onclick = startRecording;
btnStartTranslation.onclick = startTranslation;
btnStop.onclick = stopRecording;

useMicCheckbox.addEventListener('change', function () {
    // Разрешаем микрофон в любом режиме
    // Никаких уведомлений
});

useSystemCheckbox.addEventListener('change', function () {
    // Никаких уведомлений
});

// --- Логика Picture-in-Picture ---

async function openPiP() {
    if (!("documentPictureInPicture" in window)) {
        alert("Ваш браузер не поддерживает Document Picture-in-Picture API (Chrome 116+).");
        return;
    }

    try {
        pipWindow = await documentPictureInPicture.requestWindow({
            width: 800,
            height: 250, // Уменьшил высоту для компактности
        });

        // Сбрасываем стили body у PiP окна
        pipWindow.document.body.style.margin = "0";
        pipWindow.document.body.style.padding = "0";
        pipWindow.document.body.style.background = "black";
        pipWindow.document.body.style.overflow = "hidden";

        // Копируем стили
        [...document.styleSheets].forEach((styleSheet) => {
            try {
                const cssRules = [...styleSheet.cssRules].map((rule) => rule.cssText).join('');
                const style = document.createElement('style');
                style.textContent = cssRules;
                pipWindow.document.head.appendChild(style);
            } catch (e) {
                const link = document.createElement('link');
                link.rel = 'stylesheet';
                link.type = styleSheet.type;
                link.media = styleSheet.media;
                link.href = styleSheet.href;
                pipWindow.document.head.appendChild(link);
            }
        });

        // Перемещаем контейнер в PiP
        pipWindow.document.body.appendChild(pipContainer);
        pipContainer.style.display = 'flex';

        // Обработчик закрытия
        pipWindow.addEventListener("pagehide", (event) => {
            const wrapper = document.getElementById('pipWrapper');
            if (wrapper) wrapper.appendChild(pipContainer);
            pipContainer.style.display = 'none';
            pipWindow = null;
            stopRecording(); // Останавливаем запись при закрытии окна
        });

    } catch (err) {
        console.error("Не удалось открыть PiP окно:", err);
    }
}

// --- Основные функции ---

async function startRecording() {
    if (!checkAuth()) return;

    const useMic = document.getElementById('useMic').checked;
    const useSystem = document.getElementById('useSystem').checked;

    if (!useMic && !useSystem) {
        alert("Выберите хотя бы один источник звука");
        return;
    }

    setRunningUi(true);
    currentMode = 'transcription';

    try {
        statusEl.textContent = "Инициализация...";
        audioContext = new AudioContext();
        const destination = audioContext.createMediaStreamDestination();

        setupWebSocket(false);

        if (useMic) await setupMicStream(destination);
        if (useSystem) {
            const success = await setupSystemStream(destination);
            if (!success) return;
        }

    } catch (err) {
        console.error("Error starting:", err);
        statusEl.textContent = "Ошибка: " + err.message;
        stopRecording();
    }
}

async function startTranslation() {
    if (!checkAuth()) return;

    // === 1. Получаем ссылки на чекбоксы (не просто значения!) ===
    const micCheckbox = document.getElementById('useMic');
    const systemCheckbox = document.getElementById('useSystem');

    // === 2. Автоматическое отключение микрофона, если оба включены ===
    if (micCheckbox.checked && systemCheckbox.checked) {
        micCheckbox.checked = false;                                 // снимаем галочку
        statusEl.textContent = 'Микрофон автоматически отключён (используется только системный звук)';
        // можно добавить небольшой таймаут, чтобы пользователь увидел сообщение
        await new Promise(resolve => setTimeout(resolve, 1200));
    }

    // === 3. Проверка, что хоть что-то выбрано ===
    const useMic = micCheckbox.checked;
    const useSystem = systemCheckbox.checked;

    if (!useMic && !useSystem) {
        alert("Выберите хотя бы один источник звука");
        return;
    }

    // === 4. Запускаем перевод ===
    setRunningUi(true);
    currentMode = 'translation';

    try {
        await openPiP();

        statusEl.textContent = "Инициализация перевода...";
        audioContext = new AudioContext();
        const destination = audioContext.createMediaStreamDestination();

        setupWebSocket(true);

        if (useMic) await setupMicStream(destination);
        if (useSystem) {
            const success = await setupSystemStream(destination);
            if (!success) return;
        }

    } catch (err) {
        console.error("Error starting translation:", err);
        statusEl.textContent = "Ошибка: " + err.message;
        stopRecording();
    }
}

function stopRecording() {
    // Останавливаем медиа рекордеры
    if (micRecorder && micRecorder.state !== 'inactive') {
        try { micRecorder.stop(); } catch { }
    }
    if (systemRecorder && systemRecorder.state !== 'inactive') {
        try { systemRecorder.stop(); } catch { }
    }

    // Отправляем команду остановки на сервер
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "stop" }));
        statusEl.textContent = "Завершение...";
        // Не закрываем WebSocket сразу, ждем сообщение done от сервера
    } else {
        // Если WebSocket не открыт, просто очищаем ресурсы
        finalCleanup();
    }
}

function finalCleanup() {
    // Закрываем WebSocket
    if (ws) {
        try { ws.close(); } catch { }
        ws = null;
    }

    // Останавливаем медиа потоки
    stopTracks();

    // Сбрасываем состояние UI
    setRunningUi(false);

    // Очищаем interim элемент
    if (currentInterim) {
        currentInterim.remove();
        currentInterim = null;
    }

    // Закрываем PiP окно
    if (pipWindow) {
        pipWindow.close();
        pipWindow = null;
    }
    pipContainer.style.display = 'none';

    // Сбрасываем рекордеры
    micRecorder = null;
    systemRecorder = null;
    audioContext = null;
    micStream = null;
    systemStream = null;

    // Сбрасываем режим
    currentMode = 'transcription';
}

function stopTracks() {
    if (micStream) micStream.getTracks().forEach(t => t.stop());
    if (systemStream) systemStream.getTracks().forEach(t => t.stop());
    if (audioContext) audioContext.close();
}

// --- Хелперы ---

function setupWebSocket(isTranslation) {
    const token = localStorage.getItem('access_token');
    if (!token) {
        alert('Токен отсутствует. Пожалуйста, войдите снова.');
        window.location.href = 'login.html';
        return;
    }

    const wsProtocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
    const wsUrl = wsProtocol + window.location.host + '/ws/stream?token=' + encodeURIComponent(token);
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        statusEl.textContent = isTranslation ? "Перевод активен..." : "Запись идет...";

        const msg = isTranslation ? {
            type: "start_translation",
            source_lang: sourceLang.value,
            target_lang: targetLang.value,
            sample_rate: audioContext.sampleRate
        } : {
            type: "start",
            language: sourceLang.value,
            sample_rate: audioContext.sampleRate
        };

        ws.send(JSON.stringify(msg));

        if (!isTranslation) transcriptBox.innerHTML = '';
        downloadSection.style.display = 'none';

        // Очищаем PiP при старте
        pipFinalPhrases.innerHTML = '';
        pipInterimPhrase.textContent = '';
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleServerMessage(data);
    };

    ws.onclose = () => {
        if (statusEl.textContent !== "Готово") {
            statusEl.textContent = "Соединение закрыто";
        }
        stopRecording();
    };

    ws.onerror = (e) => console.error("WS Error", e);
}

async function setupMicStream(destination) {
    micStream = await navigator.mediaDevices.getUserMedia({
        audio: { deviceId: micSelect.value ? { exact: micSelect.value } : undefined }
    });
    const micSource = audioContext.createMediaStreamSource(micStream);
    micSource.connect(destination);

    micRecorder = new MediaRecorder(micStream, { mimeType: 'audio/webm;codecs=opus' });
    micRecorder.ondataavailable = async (e) => {
        if (e.data.size > 0 && ws.readyState === WebSocket.OPEN) {
            const buffer = await e.data.arrayBuffer();
            const prefixed = new Uint8Array(buffer.byteLength + 1);
            prefixed[0] = 0x00;
            prefixed.set(new Uint8Array(buffer), 1);
            ws.send(prefixed);
        }
    };
    micRecorder.start(450);
}

async function setupSystemStream(destination) {
    try {
        systemStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
    } catch (e) {
        stopRecording();
        return false;
    }

    const audioTrack = systemStream.getAudioTracks()[0];
    if (!audioTrack) {
        alert("Нет аудио! Поставьте галочку 'Share audio'.");
        stopTracks();
        stopRecording();
        return false;
    }

    systemStream.getVideoTracks()[0].onended = () => {
        stopRecording();
    };

    const sysSource = audioContext.createMediaStreamSource(new MediaStream([audioTrack]));
    sysSource.connect(destination);

    systemRecorder = new MediaRecorder(new MediaStream([audioTrack]), { mimeType: 'audio/webm;codecs=opus' });
    systemRecorder.ondataavailable = async (e) => {
        if (e.data.size > 0 && ws.readyState === WebSocket.OPEN) {
            const buffer = await e.data.arrayBuffer();
            const prefixed = new Uint8Array(buffer.byteLength + 1);
            prefixed[0] = 0x01;
            prefixed.set(new Uint8Array(buffer), 1);
            ws.send(prefixed);
        }
    };
    systemRecorder.start(450);
    return true;
}

// --- Обработка сообщений ---

function handleServerMessage(data) {
    if (data.type === "transcript") {
        renderTranscript(data);
    } else if (data.type === "translation") {
        renderTranslation(data);
    } else if (data.type === "done") {
        statusEl.textContent = "Готово";
        if (data.download_url) {
            // Используем новый формат с download_url
            // Добавляем обработчик для скачивания файла с токеном
            downloadLink.onclick = function (e) {
                e.preventDefault();
                downloadTranscription(data.transcription_id);
                return false;
            };
            downloadLink.href = "#";
            downloadLink.textContent = "Скачать транскрипцию";
            downloadSection.style.display = 'block';
        } else if (data.file_url) {
            // Обратная совместимость со старым форматом
            downloadLink.href = data.file_url;
            downloadSection.style.display = 'block';
        }
        finalCleanup();
    } else if (data.type === "error") {
        alert("Server Error: " + data.message);
    }
}

function renderTranscript(data) {
    const speaker = data.speaker ? (data.speaker === 'me' ? '🗣 Я' : '👥 Собеседник') : '';
    const text = `<span class="speaker">${speaker}</span> ${data.text}`;

    if (data.is_final) {
        if (currentInterim) { currentInterim.remove(); currentInterim = null; }
        const div = document.createElement('div');
        div.className = 'message';
        div.innerHTML = `<b>${formatTime(data.timestamp)}</b> ${text}`;
        transcriptBox.appendChild(div);
    } else {
        if (!currentInterim) {
            currentInterim = document.createElement('div');
            currentInterim.className = 'message interim';
            transcriptBox.appendChild(currentInterim);
        }
        currentInterim.innerHTML = `... ${text}`;
    }
    transcriptBox.scrollTop = transcriptBox.scrollHeight;
}

function renderTranslation(data) {
    const translated = data.translated.trim();

    // Удаляем placeholder при первом сообщении
    const placeholder = transcriptBox.querySelector('.placeholder');
    if (placeholder) placeholder.remove();

    if (data.is_final) {
        // Разбиваем на предложения
        const sentences = translated
            .split(/(?<=[.!?])\s+/)
            .map(s => s.trim())
            .filter(s => s.length > 0);

        sentences.forEach(sentence => {
            const div = document.createElement('div');
            div.className = 'pip-final-item';
            div.textContent = sentence;
            pipFinalPhrases.appendChild(div);   // ← добавляем в конец (вниз)
        });

        pipInterimPhrase.textContent = '';

        // Лимит — оставляем последние 6 строк (удаляем самые старые сверху)
        while (pipFinalPhrases.children.length > 6) {
            pipFinalPhrases.removeChild(pipFinalPhrases.firstChild);
        }

        // Скролл строго вниз к новой фразе
        pipFinalPhrases.scrollTop = pipFinalPhrases.scrollHeight;

        // Дублируем в основное окно
        const transcriptDiv = document.createElement('div');
        transcriptDiv.className = 'message translation';
        transcriptDiv.innerHTML = `<b>${formatTime(data.timestamp)}</b> ${translated}`;
        transcriptBox.appendChild(transcriptDiv);
        transcriptBox.scrollTop = transcriptBox.scrollHeight;

    } else {
        // Interim — просто обновляем нижнюю строку
        pipInterimPhrase.textContent = translated;

        if (!currentInterim) {
            currentInterim = document.createElement('div');
            currentInterim.className = 'message interim translation';
            transcriptBox.appendChild(currentInterim);
        }
        currentInterim.innerHTML = `... ${translated}`;
        transcriptBox.scrollTop = transcriptBox.scrollHeight;
    }
}

function formatTime(ts) {
    if (typeof ts === 'string' && ts.includes(':')) return ts;
    const s = Number(ts);
    if (isNaN(s)) return ts;
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, '0')}`;
}

// Функция для скачивания транскрипции
async function downloadTranscription(transcriptionId) {
    const token = localStorage.getItem('access_token');
    if (!token) {
        alert('Для скачивания транскрипции необходимо войти в систему.');
        window.location.href = 'login.html';
        return;
    }

    try {
        const response = await fetch(`/transcriptions/${transcriptionId}/download?token=${encodeURIComponent(token)}`);

        if (response.status === 401) {
            alert('Сессия истекла. Пожалуйста, войдите снова.');
            window.location.href = 'login.html';
            return;
        }

        if (!response.ok) {
            throw new Error(`Ошибка скачивания: ${response.status}`);
        }

        // Получаем имя файла из заголовков
        const contentDisposition = response.headers.get('Content-Disposition');
        let filename = `transcription_${transcriptionId}.txt`;
        if (contentDisposition) {
            const match = contentDisposition.match(/filename="(.+)"/);
            if (match) {
                filename = match[1];
            }
        }

        // Создаем blob и скачиваем
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    } catch (error) {
        console.error('Ошибка скачивания:', error);
        alert(`Ошибка скачивания: ${error.message}`);
    }
}
