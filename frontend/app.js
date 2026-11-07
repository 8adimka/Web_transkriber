// The selected workspace is independent of the session currently capturing audio.
let selectedMode = 'transcription';
let currentMode = 'transcription';
let activeSession = null;
let pipWindow = null;
let renderedView = null;
const interimElements = new Map();
let statusMessage = { key: 'workspace.ready', values: {} };
const modeViews = {
    transcription: { segments: [], interim: new Map(), completed: false, download: null },
    translation: { segments: [], interim: new Map(), completed: false, download: null }
};
const byId = id => document.getElementById(id);
const appText = (key, values = {}) => window.UI.t(key, values);
const statusEl = byId('statusBar');
const transcriptBox = byId('transcriptBox');
const resultSection = byId('resultSection');
const btnStart = byId('btnStart');
const btnStartTranslation = byId('btnStartTranslation');
const btnStop = byId('btnStop');
const micSelect = byId('micSelect');
const downloadSection = byId('downloadSection');
const downloadLink = byId('downloadLink');
const sourceLang = byId('sourceLang');
const targetLang = byId('targetLang');
const useMicCheckbox = byId('useMic');
const useSystemCheckbox = byId('useSystem');
const pipContainer = byId('pipContainer');
const pipFinalPhrases = byId('pipFinalPhrases');
const pipInterimPhrase = byId('pipInterimPhrase');
const panelIds = { transcription: 'transcriberPanel', translation: 'translatorPanel', reader: 'readerPanel' };

function setStatus(key, values = {}, error = false) {
    statusMessage = { key, values, error };
    statusEl.removeAttribute('data-i18n');
    statusEl.dataset.state = error ? 'error' : key === 'workspace.recording' || key === 'workspace.translating' ? 'recording' : 'idle';
    statusEl.textContent = appText(key, values);
    statusEl.classList.toggle('error', error);
}

function selectMode(mode, focus = false) {
    if (!(mode in panelIds)) return;
    selectedMode = mode;
    document.querySelectorAll('[data-mode]').forEach(tab => {
        const selected = tab.dataset.mode === mode;
        tab.setAttribute('aria-selected', String(selected));
        tab.tabIndex = selected ? 0 : -1;
        if (selected && focus) tab.focus();
    });
    Object.entries(panelIds).forEach(([name, id]) => { byId(id).hidden = name !== mode; });
    if (mode !== 'reader') byId(panelIds[mode]).appendChild(resultSection);
    if (!activeSession) {
        const message = modeViews[mode]?.status || { key: 'workspace.ready', values: {} };
        setStatus(message.key, message.values, message.error);
    }
    updateWorkspace();
    renderResults();
}

function updateWorkspace() {
    const running = !!activeSession;
    const stopping = running && activeSession.stopping;
    btnStart.disabled = running;
    btnStartTranslation.disabled = running;
    btnStart.hidden = selectedMode !== 'transcription' || running;
    btnStartTranslation.hidden = selectedMode !== 'translation' || running;
    btnStop.hidden = !running;
    btnStop.disabled = !!stopping;
    for (const control of [micSelect, sourceLang, targetLang, useMicCheckbox, useSystemCheckbox]) {
        control.disabled = running;
    }
    const translating = running && currentMode === 'translation';
    byId('translatorLive').hidden = !translating;
    byId('translatorHint').hidden = translating || modeViews.translation.completed;
    resultSection.hidden = selectedMode === 'reader' ||
        (selectedMode === 'translation' && !modeViews.translation.completed);
    const title = byId('resultTitle');
    title.dataset.i18n = selectedMode === 'translation' ? 'mode.translator' : 'workspace.result';
    title.textContent = appText(title.dataset.i18n);
    const view = modeViews[selectedMode];
    downloadSection.style.display = view && view.download ? 'flex' : 'none';
    if (view && view.download) {
        downloadLink.textContent = appText(view.download.id ? 'common.download' : 'workspace.localCopy');
        downloadLink.href = '#';
        downloadLink.removeAttribute('target');
        downloadLink.onclick = event => {
            event.preventDefault();
            if (view.download.id) downloadTranscription(view.download.id);
            else downloadLocalText(selectedMode);
        };
    }
}

function makeMessage(segment, interim = false) {
    const element = document.createElement('div');
    element.className = `message${interim ? ' interim' : ''}${segment.translated !== undefined ? ' translation' : ''}`;
    if (segment.timestamp || segment.speaker) {
        const meta = document.createElement('div');
        meta.className = 'message-meta';
        const time = document.createElement('time');
        time.textContent = formatTime(segment.timestamp || '');
        meta.appendChild(time);
        if (segment.speaker) {
            const speaker = document.createElement('span');
            speaker.className = 'speaker';
            speaker.textContent = appText(segment.speaker === 'me' ? 'workspace.speakerMe' : 'workspace.speakerOther');
            meta.appendChild(speaker);
        }
        element.appendChild(meta);
    }
    const text = document.createElement('p');
    text.textContent = segment.translated !== undefined ? segment.translated : segment.text;
    element.appendChild(text);
    return element;
}

function renderResults() {
    const view = modeViews[selectedMode];
    if (!view || resultSection.hidden) return;
    renderedView = view;
    interimElements.clear();
    const fragment = document.createDocumentFragment();
    for (const segment of view.segments) fragment.appendChild(makeMessage(segment));
    for (const [source, segment] of view.interim) {
        const node = makeMessage(segment, true);
        interimElements.set(source, node);
        fragment.appendChild(node);
    }
    if (!fragment.childNodes.length) {
        const placeholder = document.createElement('div');
        placeholder.className = 'placeholder';
        if (selectedMode === 'transcription') {
            const wave = document.createElement('div');
            wave.className = 'waveform';
            wave.setAttribute('aria-hidden', 'true');
            for (let index = 0; index < 7; index++) wave.appendChild(document.createElement('i'));
            const title = document.createElement('strong');
            title.textContent = appText('workspace.placeholderTitle');
            placeholder.append(wave, title);
        }
        const description = document.createElement('p');
        description.textContent = appText(selectedMode === 'translation' ? 'workspace.emptyTranslation' : 'workspace.placeholder');
        placeholder.appendChild(description);
        fragment.appendChild(placeholder);
    }
    transcriptBox.replaceChildren(fragment);
    transcriptBox.scrollTop = transcriptBox.scrollHeight;
}

function renderIncoming(segment, source, mode, final) {
    const view = modeViews[mode];
    if (selectedMode !== mode || resultSection.hidden) return;
    if (renderedView !== view) { renderResults(); return; }
    transcriptBox.querySelector('.placeholder')?.remove();
    const previous = interimElements.get(source);
    if (final) {
        previous?.remove();
        interimElements.delete(source);
        if ((segment.translated ?? segment.text).trim()) transcriptBox.appendChild(makeMessage(segment));
    } else {
        const node = makeMessage(segment, true);
        if (previous) previous.replaceWith(node);
        else transcriptBox.appendChild(node);
        interimElements.set(source, node);
    }
    transcriptBox.scrollTop = transcriptBox.scrollHeight;
}

async function loadDevices() {
    // Enumerating devices must not leave an extra microphone stream running.
    if (!navigator.mediaDevices?.enumerateDevices) return;
    try {
        const selected = micSelect.value;
        const devices = await navigator.mediaDevices.enumerateDevices();
        micSelect.replaceChildren();
        const defaultOption = document.createElement('option');
        defaultOption.value = '';
        defaultOption.textContent = appText('workspace.defaultMicrophone');
        micSelect.appendChild(defaultOption);
        devices.filter(device => device.kind === 'audioinput').forEach((device, index) => {
            if (!device.deviceId) return;
            const option = document.createElement('option');
            option.value = device.deviceId;
            option.textContent = device.label || appText('audio.microphone') + ` ${index + 1}`;
            micSelect.appendChild(option);
        });
        if ([...micSelect.options].some(option => option.value === selected)) micSelect.value = selected;
    } catch {
        setStatus('workspace.microphoneDenied', {}, true);
    }
}

function syncPipAppearance() {
    if (!pipWindow || pipWindow.closed) return;
    pipWindow.document.documentElement.dataset.theme = window.UI.theme;
    pipWindow.document.documentElement.lang = window.UI.language;
    pipWindow.document.title = appText('mode.translator');
    window.UI.translate(pipWindow.document);
}

async function openPiP(session) {
    try {
        const floatingWindow = window.documentPictureInPicture?.requestWindow
            ? await window.documentPictureInPicture.requestWindow({ width: 800, height: 260 })
            : window.open('', 'transcriber-subtitles', 'popup,width=800,height=300');
        if (!floatingWindow) throw new Error('Popup unavailable');
        if (session.finished || activeSession !== session) { floatingWindow.close(); return false; }
        pipWindow = floatingWindow;
        const floatingDocument = floatingWindow.document;
        floatingDocument.body.replaceChildren();
        floatingDocument.body.className = 'pip-body';
        for (const styleSheet of document.styleSheets) {
            try {
                const style = floatingDocument.createElement('style');
                style.textContent = [...styleSheet.cssRules].map(rule => rule.cssText).join('\n');
                floatingDocument.head.appendChild(style);
            } catch {
                if (!styleSheet.href) continue;
                const link = floatingDocument.createElement('link');
                link.rel = 'stylesheet';
                link.href = styleSheet.href;
                floatingDocument.head.appendChild(link);
            }
        }
        floatingDocument.body.appendChild(pipContainer);
        pipContainer.style.display = 'flex';
        syncPipAppearance();
        floatingWindow.addEventListener('pagehide', () => {
            byId('pipWrapper').appendChild(pipContainer);
            pipContainer.style.display = 'none';
            if (pipWindow === floatingWindow) pipWindow = null;
            if (activeSession === session && !session.finished && !session.stopping) stopRecording();
        }, { once: true });
        return true;
    } catch {
        setStatus('workspace.pipUnavailable', {}, true);
        return false;
    }
}

async function startRecording() { return startSession('transcription'); }
async function startTranslation() { return startSession('translation'); }

async function startSession(mode) {
    if (activeSession) return;
    if (!window.auth.isAuthenticated()) {
        setStatus('workspace.loginRequired', {}, true);
        window.location.href = 'login.html';
        return;
    }
    if (!useMicCheckbox.checked && !useSystemCheckbox.checked) {
        setStatus('workspace.selectSource', {}, true);
        return;
    }
    if (!navigator.mediaDevices || !window.AudioContext || !window.MediaRecorder) {
        setStatus('workspace.mediaUnsupported', {}, true);
        return;
    }
    if (!MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
        setStatus('workspace.recordingUnsupported', {}, true);
        return;
    }
    if (mode === 'translation' && useMicCheckbox.checked && useSystemCheckbox.checked) {
        // The translator consumes one source; prefer the shared tab, as before.
        useMicCheckbox.checked = false;
    }
    currentMode = mode;
    selectMode(mode);
    const session = {
        mode, socket: null, recorders: [], recorderStops: new Map(), startedRecorders: new Set(), streams: [], context: null,
        sendQueue: Promise.resolve(), finished: false, stopping: false,
        completionTimer: null, stopPromise: null, saveFailed: false
    };
    activeSession = session;
    const view = modeViews[mode];
    view.segments = [];
    view.interim.clear();
    view.completed = false;
    view.download = null;
    pipFinalPhrases.replaceChildren();
    pipInterimPhrase.textContent = '';
    updateWorkspace();
    renderResults();
    setStatus('workspace.initializing');
    try {
        if (mode === 'translation' && !(await openPiP(session))) {
            completeSession(session, 'workspace.pipUnavailable', true);
            return;
        }
        if (session.finished) return;
        session.context = new AudioContext();
        await session.context.resume();
        if (useMicCheckbox.checked) await setupMicStream(session);
        if (!session.finished && useSystemCheckbox.checked) {
            if (mode === 'translation') await chooseSharedAudio(session);
            else await setupSystemStream(session);
        }
        if (session.finished) return;
        await setupWebSocket(session);
        if (session.finished || session.stopping) return;
        for (const recorder of session.recorders) {
            recorder.start(450);
            session.startedRecorders.add(recorder);
        }
        setStatus(mode === 'translation' ? 'workspace.translating' : 'workspace.recording');
        loadDevices();
    } catch (error) {
        if (!session.finished) completeSession(session, error.name === 'NotAllowedError' ? 'workspace.captureDenied' :
            error.code || 'workspace.sourceUnavailable', true);
    }
}

function ownStream(session, stream) {
    if (session.finished || session.stopping) {
        stream.getTracks().forEach(track => track.stop());
        throw new Error('Cancelled capture');
    }
    session.streams.push(stream);
    return stream;
}

async function setupMicStream(session) {
    const stream = ownStream(session, await navigator.mediaDevices.getUserMedia({
        audio: { deviceId: micSelect.value ? { exact: micSelect.value } : undefined }
    }));
    createRecorder(session, stream, 0);
}

async function setupSystemStream(session, devices = navigator.mediaDevices) {
    const stream = ownStream(session, await devices.getDisplayMedia({ video: true, audio: true }));
    const track = stream.getAudioTracks()[0];
    if (!track) {
        const error = new Error('No shared audio');
        error.code = 'workspace.noSystemAudio';
        throw error;
    }
    const video = stream.getVideoTracks()[0];
    if (video) video.addEventListener('ended', () => {
        if (activeSession === session && !session.finished) stopRecording();
    }, { once: true });
    createRecorder(session, new MediaStream([track]), 1);
}

function chooseSharedAudio(session) {
    // PiP and screen capture both consume activation. The second user action
    // belongs in the floating window, whose document has focus for the chooser.
    // https://wicg.github.io/document-picture-in-picture/#api
    // https://www.w3.org/TR/screen-capture/#dom-mediadevices-getdisplaymedia
    return new Promise((resolve, reject) => {
        const floatingWindow = pipWindow;
        const prompt = document.createElement('div');
        prompt.className = 'pip-setup';
        const description = document.createElement('p');
        description.dataset.i18n = 'workspace.shareAudioHint';
        description.textContent = appText('workspace.shareAudioHint');
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'button primary';
        button.dataset.shareAudio = '';
        button.dataset.i18n = 'workspace.shareAudio';
        button.textContent = appText('workspace.shareAudio');
        prompt.append(description, button);
        pipContainer.prepend(prompt);
        session.cancelAudioSelection = () => { prompt.remove(); reject(new Error('Cancelled capture')); };
        button.addEventListener('click', async () => {
            button.disabled = true;
            try {
                await setupSystemStream(session, floatingWindow.navigator?.mediaDevices || navigator.mediaDevices);
                prompt.remove();
                session.cancelAudioSelection = null;
                resolve();
            } catch (error) {
                prompt.remove();
                session.cancelAudioSelection = null;
                reject(error);
            }
        }, { once: true });
    });
}

function createRecorder(session, stream, source) {
    const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
    session.recorderStops.set(recorder, new Promise(resolve => {
        recorder.addEventListener('stop', resolve, { once: true });
    }));
    recorder.addEventListener('dataavailable', event => {
        if (!event.data.size || session.finished) return;
        session.sendQueue = session.sendQueue.then(async () => {
            const buffer = await event.data.arrayBuffer();
            if (session.finished || session.socket?.readyState !== WebSocket.OPEN) return;
            const bytes = new Uint8Array(buffer.byteLength + 1);
            bytes[0] = source;
            bytes.set(new Uint8Array(buffer), 1);
            session.socket.send(bytes);
        }).catch(() => {
            if (!session.finished) completeSession(session, 'workspace.connectionClosed', true);
        });
    });
    session.recorders.push(recorder);
}

function setupWebSocket(session) {
    return new Promise((resolve, reject) => {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const token = window.auth.getAccessToken();
        const socket = new WebSocket(`${protocol}//${window.location.host}/ws/stream?token=${encodeURIComponent(token)}`);
        session.socket = socket;
        const timer = setTimeout(() => reject(new Error('Connection timeout')), 10000);
        socket.onopen = () => {
            clearTimeout(timer);
            if (session.finished || session.stopping) { socket.close(); resolve(); return; }
            socket.send(JSON.stringify(session.mode === 'translation' ? {
                type: 'start_translation', source_lang: sourceLang.value,
                target_lang: targetLang.value, sample_rate: session.context.sampleRate
            } : {
                type: 'start', language: sourceLang.value,
                target_lang: targetLang.value, sample_rate: session.context.sampleRate
            }));
            resolve();
        };
        socket.onmessage = event => {
            if (session.finished) return;
            try { handleServerMessage(JSON.parse(event.data), session); }
            catch { setStatus('workspace.providerError', { message: appText('common.error') }, true); }
        };
        socket.onerror = () => {
            clearTimeout(timer);
            reject(new Error('Connection failed'));
            if (!session.finished) completeSession(session, 'workspace.connectionClosed', true);
        };
        socket.onclose = () => {
            clearTimeout(timer);
            reject(new Error('Connection closed'));
            if (!session.finished) completeSession(session, 'workspace.connectionClosed', true);
        };
    });
}

async function stopRecording() {
    const session = activeSession;
    if (!session || session.finished) return;
    if (session.stopPromise) return session.stopPromise;
    session.stopping = true;
    setStatus('workspace.stopping');
    updateWorkspace();
    session.stopPromise = (async () => {
        // The stop event follows the last dataavailable; await its async conversion too.
        await Promise.all(session.recorders.map(recorder => {
            if (!session.startedRecorders.has(recorder)) return Promise.resolve();
            if (recorder.state !== 'inactive') {
                try { recorder.stop(); } catch { return Promise.resolve(); }
            }
            // A source may already be inactive while its final events are queued.
            return session.recorderStops.get(recorder);
        }));
        await session.sendQueue;
        if (session.finished) return;
        for (const stream of session.streams) stream.getTracks().forEach(track => track.stop());
        if (session.socket?.readyState === WebSocket.OPEN) {
            session.socket.send(JSON.stringify({ type: 'stop' }));
            session.completionTimer = setTimeout(() => completeSession(session, 'workspace.stopTimeout', true), 60000);
        } else {
            completeSession(session, 'workspace.connectionClosed', !!modeViews[session.mode].segments.length);
        }
    })();
    return session.stopPromise;
}

function completeSession(session, key = 'workspace.done', error = false) {
    if (session.finished) return;
    session.finished = true;
    session.cancelAudioSelection?.();
    session.cancelAudioSelection = null;
    clearTimeout(session.completionTimer);
    for (const recorder of session.recorders) {
        if (recorder.state !== 'inactive') { try { recorder.stop(); } catch { /* already stopped */ } }
    }
    for (const stream of session.streams) stream.getTracks().forEach(track => track.stop());
    if (session.context && session.context.state !== 'closed') session.context.close().catch(() => {});
    if (session.socket) session.socket.close();
    if (pipWindow) {
        const floatingWindow = pipWindow;
        pipWindow = null;
        byId('pipWrapper').appendChild(pipContainer);
        pipContainer.style.display = 'none';
        floatingWindow.close();
    }
    const view = modeViews[session.mode];
    view.completed = true;
    view.interim.clear();
    if (!view.download && view.segments.length) view.download = { local: true };
    view.status = { key, values: {}, error };
    if (activeSession === session) activeSession = null;
    const message = modeViews[selectedMode]?.status || { key: 'workspace.ready', values: {} };
    setStatus(message.key, message.values, message.error);
    updateWorkspace();
    renderResults();
}

function handleServerMessage(data, session = activeSession) {
    if (!session || session.finished) return;
    if (data.type === 'transcript' || data.type === 'translation') {
        const view = modeViews[session.mode];
        const segment = { ...data, text: String(data.text || ''), timestamp: data.timestamp || '' };
        if (data.type === 'translation') segment.translated = String(data.translated || '').trim();
        const source = data.speaker || 'translation';
        if (data.is_final) {
            view.interim.delete(source);
            if ((segment.translated ?? segment.text).trim()) view.segments.push(segment);
        } else view.interim.set(source, segment);
        if (data.type === 'translation') renderTranslation(segment);
        renderIncoming(segment, source, session.mode, data.is_final);
    } else if (data.type === 'done') {
        const view = modeViews[session.mode];
        if (data.transcription_id && data.download_url) view.download = { id: data.transcription_id };
        const failed = session.saveFailed || (data.saved === false && !data.empty && view.segments.length > 0);
        completeSession(session, failed ? 'workspace.saveFailed' :
            data.incomplete ? 'workspace.stopTimeout' : 'workspace.done', failed || !!data.incomplete);
    } else if (data.type === 'error') {
        if (data.code === 'save_failed') session.saveFailed = true;
        setStatus(data.code === 'save_failed' ? 'workspace.saveFailed' : 'workspace.providerError',
            { message: window.UI.t(data.message || 'common.error') }, true);
    }
}

function renderTranslation(data) {
    if (data.is_final) {
        for (const sentence of data.translated.split(/(?<=[.!?])\s+/).filter(Boolean)) {
            const line = document.createElement('div');
            line.className = 'pip-final-item';
            line.textContent = sentence;
            pipFinalPhrases.appendChild(line);
        }
        pipInterimPhrase.textContent = '';
        // Only the floating viewport is shortened; the complete result stays in modeViews.
        while (pipFinalPhrases.children.length > 6) pipFinalPhrases.firstElementChild.remove();
        pipFinalPhrases.scrollTop = pipFinalPhrases.scrollHeight;
    } else pipInterimPhrase.textContent = data.translated;
}

function formatTime(timestamp) {
    if (typeof timestamp === 'string' && timestamp.includes(':')) return timestamp;
    const seconds = Number(timestamp);
    return Number.isFinite(seconds) ? `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}` : '';
}

function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function downloadLocalText(mode) {
    const text = modeViews[mode].segments.map(segment =>
        [segment.timestamp, segment.translated ?? segment.text].filter(Boolean).join(' ')).join('\n\n');
    saveBlob(new Blob([text], { type: 'text/plain;charset=utf-8' }), `${mode}_${new Date().toISOString().replace(/[:.]/g, '-')}.txt`);
}

async function downloadTranscription(id, retried = false) {
    try {
        const token = window.auth.getAccessToken();
        const response = await fetch(`/transcriptions/${encodeURIComponent(id)}/download?token=${encodeURIComponent(token)}`);
        if (response.status === 401 && !retried && window.auth.refreshAccessToken) {
            if (await window.auth.refreshAccessToken()) return downloadTranscription(id, true);
        }
        if (!response.ok) throw new Error(String(response.status));
        const disposition = response.headers.get('Content-Disposition') || '';
        const match = disposition.match(/filename="?([^";]+)"?/);
        saveBlob(await response.blob(), match ? match[1] : `text_${id}.txt`);
    } catch {
        setStatus('workspace.downloadFailed', { message: appText('workspace.connectionClosed') }, true);
    }
}

btnStart.addEventListener('click', startRecording);
btnStartTranslation.addEventListener('click', startTranslation);
btnStop.addEventListener('click', stopRecording);
const tabs = [...document.querySelectorAll('[data-mode]')];
tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => selectMode(tab.dataset.mode));
    tab.addEventListener('keydown', event => {
        let next;
        if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
        else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
        else if (event.key === 'Home') next = 0;
        else if (event.key === 'End') next = tabs.length - 1;
        else return;
        event.preventDefault();
        selectMode(tabs[next].dataset.mode, true);
    });
});
document.addEventListener('ui:change', () => {
    setStatus(statusMessage.key, statusMessage.values, statusMessage.error);
    syncPipAppearance();
    loadDevices();
    updateWorkspace();
    renderResults();
});
window.addEventListener('pagehide', () => {
    if (activeSession) completeSession(activeSession);
});
if (!window.auth.isAuthenticated()) window.location.href = 'login.html';
loadDevices();
selectMode('transcription');
