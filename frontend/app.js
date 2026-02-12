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

// Элементы PiP (будут привязаны при открытии окна)
const pipContainer = document.getElementById('pipContainer');
const pipFinalPhrases = document.getElementById('pipFinalPhrases');
const pipInterimPhrase = document.getElementById('pipInterimPhrase');
let pipWindow = null;

// Режим работы
let currentMode = 'transcription';
let currentInterim = null;

// Загрузка устройств
async function loadDevices() {
    try {
        await navigator.mediaDevices.getUserMedia({ audio: true });
        const devices = await navigator.mediaDevices.enumerateDevices();
        const mics = devices.filter(d => d.kind === 'audioinput');
        micSelect.innerHTML = mics.map(m => `<option value="${m.deviceId}">${m.label || 'Microphone ' + m.deviceId}</option>`).join('');
    } catch (e) {
        console.error("Access denied", e);
        statusEl.textContent = "Ошибка доступа к микрофону";
    }
}
loadDevices();

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
    if (currentMode === 'translation') {
        this.checked = false;
        alert('В режиме перевода микрофон отключен.');
    }
});

useSystemCheckbox.addEventListener('change', function () {
    if (currentMode === 'translation' && !this.checked) {
        this.checked = true;
        alert('В режиме перевода требуется звук системы.');
    }
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
            height: 300, // Увеличил высоту для комфортного чтения истории
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
    setRunningUi(true);
    currentMode = 'translation';

    useMicCheckbox.checked = false;
    useSystemCheckbox.checked = true;

    try {
        await openPiP();

        statusEl.textContent = "Инициализация перевода...";
        audioContext = new AudioContext();
        const destination = audioContext.createMediaStreamDestination();

        setupWebSocket(true);

        const success = await setupSystemStream(destination);
        if (!success) return;

    } catch (err) {
        console.error("Error starting translation:", err);
        statusEl.textContent = "Ошибка: " + err.message;
        stopRecording();
    }
}

function stopRecording() {
    if (micRecorder && micRecorder.state !== 'inactive') micRecorder.stop();
    if (systemRecorder && systemRecorder.state !== 'inactive') systemRecorder.stop();

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "stop" }));
        statusEl.textContent = "Завершение...";
    }

    stopTracks();
    setRunningUi(false);

    if (pipWindow) {
        pipWindow.close();
        pipWindow = null;
    }
    pipContainer.style.display = 'none';
}

function stopTracks() {
    if (micStream) micStream.getTracks().forEach(t => t.stop());
    if (systemStream) systemStream.getTracks().forEach(t => t.stop());
    if (audioContext) audioContext.close();
}

// --- Хелперы ---

function setupWebSocket(isTranslation) {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
    const wsUrl = wsProtocol + window.location.host + '/ws/stream';
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
        if (statusEl.textContent !== "Готово. Файл сохранен.") {
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
        statusEl.textContent = "Готово. Файл сохранен.";
        if (data.file_url) {
            downloadLink.href = data.file_url;
            downloadSection.style.display = 'block';
        }
        stopRecording();
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
    // Рендер перевода в PiP (с историей и отступами)

    if (data.is_final) {
        // 1. Создаем элемент финальной фразы
        const div = document.createElement('div');
        div.className = 'pip-final-item';
        div.textContent = data.translated;

        // Добавляем в список истории
        pipFinalPhrases.appendChild(div);

        // 2. Очищаем поле interim (фраза завершена)
        pipInterimPhrase.textContent = '';

        // 3. Лимит истории (удаляем самые старые сверху)
        // Держим ~5-6 последних фраз, чтобы не переполнять окно
        while (pipFinalPhrases.children.length > 6) {
            pipFinalPhrases.removeChild(pipFinalPhrases.firstChild);
        }

    } else {
        // Промежуточная фраза - обновляем нижнюю строку
        pipInterimPhrase.textContent = data.translated;
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
