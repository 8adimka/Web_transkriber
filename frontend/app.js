let ws = null;
let mediaRecorder = null;
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

        // 1. Захват микрофона
        if (useMic) {
            micStream = await navigator.mediaDevices.getUserMedia({
                audio: { deviceId: micSelect.value ? { exact: micSelect.value } : undefined }
            });
            const micSource = audioContext.createMediaStreamSource(micStream);
            micSource.connect(destination);
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

            const sysSource = audioContext.createMediaStreamSource(systemStream);
            sysSource.connect(destination);
        }

        // Подключение WebSocket
        // Для локального Docker: ws://localhost:8000/ws/stream
        const wsUrl = (window.location.protocol === 'https:' ? 'wss://' : 'ws://') + 'localhost:8000/ws/stream';
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            statusEl.textContent = "Соединение установлено. Запись...";
            ws.send(JSON.stringify({ type: "start", sample_rate: audioContext.sampleRate }));

            // Настройка MediaRecorder (Opus/WebM)
            mediaRecorder = new MediaRecorder(destination.stream, {
                mimeType: 'audio/webm;codecs=opus'
            });

            mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0 && ws.readyState === WebSocket.OPEN) {
                    ws.send(event.data);
                }
            };

            // Отправляем чанки каждые 450ms
            mediaRecorder.start(450);

            btnStart.disabled = true;
            btnStop.disabled = false;
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
            console.error(e);
            statusEl.textContent = "Ошибка WebSocket";
        };

    } catch (err) {
        console.error("Error starting:", err);
        statusEl.textContent = "Ошибка запуска: " + err.message;
        stopTracks();
    }
}

function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop();
    }
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "stop" }));
        statusEl.textContent = "Завершение обработки...";
    }
    btnStart.disabled = false;
    btnStop.disabled = true;
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
        if (data.is_final) {
            // Удаляем временный, добавляем финальный
            if (currentInterim) {
                currentInterim.remove();
                currentInterim = null;
            }
            const div = document.createElement('div');
            div.className = 'message';
            div.innerHTML = `<b>${formatTime(data.timestamp)}:</b> ${data.text}`;
            transcriptBox.appendChild(div);
        } else {
            // Обновляем временный
            if (!currentInterim) {
                currentInterim = document.createElement('div');
                currentInterim.className = 'message interim';
                transcriptBox.appendChild(currentInterim);
            }
            currentInterim.innerHTML = `... ${data.text}`;
        }
        transcriptBox.scrollTop = transcriptBox.scrollHeight;
    }
    else if (data.type === "done") {
        statusEl.textContent = "Готово. Файл сохранен.";
        downloadLink.href = 'http://localhost:8000' + data.file_url;
        downloadSection.style.display = 'block';
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

function formatTime(seconds) {
    const min = Math.floor(seconds / 60);
    const sec = Math.floor(seconds % 60);
    return `${min}:${sec < 10 ? '0' + sec : sec}`;
}
