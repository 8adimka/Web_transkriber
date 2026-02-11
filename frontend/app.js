let ws = null;
let micRecorder = null;
let systemRecorder = null;
let audioContext = null;
let micStream = null;
let systemStream = null;

const statusEl = document.getElementById('statusBar');
const transcriptBox = document.getElementById('transcriptBox');
const btnStart = document.getElementById('btnStart');
const btnStop = document.getElementById('btnStop');
const micSelect = document.getElementById('micSelect');
const downloadSection = document.getElementById('downloadSection');
const downloadLink = document.getElementById('downloadLink');

// Загрузка списка микрофонов
async function loadDevices() {
    try {
        await navigator.mediaDevices.getUserMedia({ audio: true }); // Request perm
        const devices = await navigator.mediaDevices.enumerateDevices();
        const mics = devices.filter(d => d.kind === 'audioinput');
        micSelect.innerHTML = mics.map(m => `<option value="${m.deviceId}">${m.label || 'Microphone ' + m.deviceId}</option>`).join('');
    } catch (e) {
        console.error("Access denied", e);
        statusEl.textContent = "Ошибка доступа к микрофону";
    }
}
loadDevices();

btnStart.onclick = startRecording;
btnStop.onclick = stopRecording;

async function startRecording() {
    const useMic = document.getElementById('useMic').checked;
    const useSystem = document.getElementById('useSystem').checked;

    if (!useMic && !useSystem) {
        alert("Выберите хотя бы один источник звука");
        return;
    }

    try {
        statusEl.textContent = "Инициализация...";
        audioContext = new AudioContext();
        const destination = audioContext.createMediaStreamDestination();

        // Подключение WebSocket через nginx прокси
        const wsProtocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
        const wsHost = window.location.host; // Используем тот же хост, что и фронтенд
        const wsUrl = wsProtocol + wsHost + '/ws/stream';
        ws = new WebSocket(wsUrl);

        ws.onopen = async () => {
            statusEl.textContent = "Соединение установлено. Запись...";
            ws.send(JSON.stringify({ type: "start", sample_rate: audioContext.sampleRate }));

            // 1. Захват микрофона
            if (useMic) {
                micStream = await navigator.mediaDevices.getUserMedia({
                    audio: { deviceId: micSelect.value ? { exact: micSelect.value } : undefined }
                });
                const micSource = audioContext.createMediaStreamSource(micStream);
                micSource.connect(destination);

                // Проверяем поддерживаемые MIME типы
                const mimeType = 'audio/webm;codecs=opus';
                if (!MediaRecorder.isTypeSupported(mimeType)) {
                    console.warn(`MIME type ${mimeType} not supported, using default`);
                }

                // Создаем MediaRecorder для микрофона
                micRecorder = new MediaRecorder(micStream, {
                    mimeType: mimeType
                });

                micRecorder.ondataavailable = async (event) => {
                    if (event.data.size > 0 && ws.readyState === WebSocket.OPEN) {
                        console.log(`Mic chunk size: ${event.data.size}`);
                        // Префикс 0x00 для микрофона
                        const arrayBuffer = await event.data.arrayBuffer();
                        const prefixedData = new Uint8Array(arrayBuffer.byteLength + 1);
                        prefixedData[0] = 0x00; // Маркер источника: 0 = микрофон
                        prefixedData.set(new Uint8Array(arrayBuffer), 1);
                        ws.send(prefixedData);
                    }
                };

                micRecorder.start(450);
                console.log("Mic recorder started");
            }

            // 2. Захват системы (getDisplayMedia)
            if (useSystem) {
                // Внимание: Чтобы захватить аудио, пользователь должен поставить галочку "Share audio" в диалоге браузера
                systemStream = await navigator.mediaDevices.getDisplayMedia({
                    video: true, // Видео обязательно для getDisplayMedia, но мы его игнорируем
                    audio: true
                });

                // Если пользователь выбрал вкладку без аудио
                const audioTrack = systemStream.getAudioTracks()[0];
                if (!audioTrack) {
                    alert("Выбранный источник не содержит аудио. Убедитесь, что поставили галочку 'Share audio'");
                    stopTracks();
                    return;
                }

                // Создаем MediaStream только с аудио дорожкой для записи
                const systemAudioStream = new MediaStream([audioTrack]);
                const sysSource = audioContext.createMediaStreamSource(systemStream);
                sysSource.connect(destination);

                // Проверяем поддерживаемые MIME типы
                const mimeType = 'audio/webm;codecs=opus';

                // Создаем MediaRecorder для системного звука
                systemRecorder = new MediaRecorder(systemAudioStream, {
                    mimeType: mimeType
                });

                systemRecorder.ondataavailable = async (event) => {
                    if (event.data.size > 0 && ws.readyState === WebSocket.OPEN) {
                        console.log(`System chunk size: ${event.data.size}`);
                        // Префикс 0x01 для системного звука
                        const arrayBuffer = await event.data.arrayBuffer();
                        const prefixedData = new Uint8Array(arrayBuffer.byteLength + 1);
                        prefixedData[0] = 0x01; // Маркер источника: 1 = системный звук
                        prefixedData.set(new Uint8Array(arrayBuffer), 1);
                        ws.send(prefixedData);
                    }
                };

                systemRecorder.start(450);
                console.log("System recorder started");
            }

            btnStart.style.display = 'none';
            btnStop.style.display = 'inline-block';
            transcriptBox.innerHTML = ''; // Очистка
            downloadSection.style.display = 'none';
        };

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            handleServerMessage(data);
        };

        ws.onclose = () => {
            statusEl.textContent = "Соединение закрыто";
            stopTracks();
        };

        ws.onerror = (e) => {
            console.error("WebSocket error:", e);
            statusEl.textContent = "Ошибка WebSocket";
        };

    } catch (err) {
        console.error("Error starting:", err);
        statusEl.textContent = "Ошибка запуска: " + err.message;
        stopTracks();
    }
}

function stopRecording() {
    if (micRecorder && micRecorder.state !== 'inactive') {
        micRecorder.stop();
    }
    if (systemRecorder && systemRecorder.state !== 'inactive') {
        systemRecorder.stop();
    }
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "stop" }));
        statusEl.textContent = "Завершение обработки...";
    }
    btnStart.style.display = 'inline-block';
    btnStop.style.display = 'none';
    stopTracks();
}

function stopTracks() {
    if (micStream) micStream.getTracks().forEach(t => t.stop());
    if (systemStream) systemStream.getTracks().forEach(t => t.stop());
    if (audioContext) audioContext.close();
}

let currentInterim = null;

function handleServerMessage(data) {
    if (data.type === "transcript") {
        // Добавляем метку источника, если есть
        const speaker = data.speaker ? (data.speaker === 'me' ? '🗣 Я' : '👥 Собеседник') : '';
        const speakerPrefix = speaker ? `<span class="speaker">${speaker}:</span> ` : '';

        if (data.is_final) {
            // Удаляем временный, добавляем финальный
            if (currentInterim) {
                currentInterim.remove();
                currentInterim = null;
            }
            const div = document.createElement('div');
            div.className = 'message';
            div.innerHTML = `<b>${formatTime(data.timestamp)}</b> ${speakerPrefix}${data.text}`;
            transcriptBox.appendChild(div);
        } else {
            // Обновляем временный
            if (!currentInterim) {
                currentInterim = document.createElement('div');
                currentInterim.className = 'message interim';
                transcriptBox.appendChild(currentInterim);
            }
            currentInterim.innerHTML = `... ${speakerPrefix}${data.text}`;
        }
        transcriptBox.scrollTop = transcriptBox.scrollHeight;
    }
    else if (data.type === "done") {
        statusEl.textContent = "Готово. Файл сохранен.";
        // Используем текущий протокол и хост для скачивания
        downloadLink.href = window.location.protocol + '//' + window.location.host + data.file_url;
        downloadSection.style.display = 'block';
        // После завершения показываем кнопку "Начать запись" (уже показана) и скрываем "Остановить"
        btnStart.style.display = 'inline-block';
        btnStop.style.display = 'none';
        ws.close();
    }
    else if (data.type === "throttle") {
        console.warn("Server asked to slow down");
        // В реальном приложении можно увеличить интервал mediaRecorder, 
        // но mediaRecorder.requestData() не меняет интервал динамически легко без перезапуска.
    }
    else if (data.type === "error") {
        alert("Server Error: " + data.message);
    }
}

function formatTime(timestamp) {
    // Если timestamp - это строка в формате HH:MM:SS, просто возвращаем ее
    if (typeof timestamp === 'string' && timestamp.includes(':')) {
        return timestamp;
    }

    // Если timestamp - это число (секунды), преобразуем в MM:SS
    const seconds = Number(timestamp);
    if (!isNaN(seconds)) {
        const min = Math.floor(seconds / 60);
        const sec = Math.floor(seconds % 60);
        return `${min}:${sec < 10 ? '0' + sec : sec}`;
    }

    // Если не можем распарсить, возвращаем исходное значение
    return timestamp;
}
