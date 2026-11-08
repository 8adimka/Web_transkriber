// Dependency-free browser regression checks. Only synthetic REST/WS/media are used.
// Run: node --test tests/frontend_ui.test.cjs (Chrome/Chromium must be installed).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createServer } = require('node:http');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');

const root = path.resolve(__dirname, '..');
const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
const defaults = { microphone_enabled: false, tab_audio_enabled: true, original_language: 'EN', translation_language: 'RU', ui_language: 'en', theme: 'dark' };

const browserMocks = `(() => {
    if (!localStorage.getItem('__ui_test_initialized')) {
        localStorage.clear();
        localStorage.setItem('__ui_test_initialized', 'yes');
        localStorage.setItem('access_token', 'synthetic-access');
        localStorage.setItem('refresh_token', 'synthetic-refresh');
        localStorage.setItem('user_info', JSON.stringify({ id: 42, email: 'demo@example.test', full_name: 'Alex Morgan', auth_provider: 'local' }));
    }
    window.__fake = { frames: [], sockets: [], tracks: [], noAudio: false, denied: false, saved: true };
    class Track extends EventTarget {
        constructor(kind) { super(); this.kind = kind; this.stopped = false; __fake.tracks.push(this); }
        stop() { this.stopped = true; }
    }
    class Stream {
        constructor(tracks) { this.tracks = tracks; }
        getTracks() { return this.tracks; }
        getAudioTracks() { return this.tracks.filter(t => t.kind === 'audio'); }
        getVideoTracks() { return this.tracks.filter(t => t.kind === 'video'); }
    }
    window.MediaStream = Stream;
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: {
        enumerateDevices: async () => [{kind:'audioinput',deviceId:'microphone-test',label:'Test microphone'}],
        getUserMedia: async () => {
            if (__fake.denied) throw new DOMException('Synthetic permission denied', 'NotAllowedError');
            return new Stream([new Track('audio')]);
        },
        getDisplayMedia: async () => new Stream(__fake.noAudio ? [new Track('video')] : [new Track('audio'),new Track('video')])
    }});
    window.AudioContext = class {
        constructor() { this.sampleRate = 48000; this.state = 'running'; }
        async resume() {}
        async close() { this.state = 'closed'; }
    };
    window.MediaRecorder = class extends EventTarget {
        static isTypeSupported() { return true; }
        constructor(stream) { super(); this.stream = stream; this.state = 'inactive'; }
        start() { this.state = 'recording'; }
        stop() {
            this.state = 'inactive';
            setTimeout(() => {
                const event = new Event('dataavailable');
                Object.defineProperty(event, 'data', { value: { size: 2, arrayBuffer: async () => {
                    await new Promise(resolve => setTimeout(resolve, 30));
                    return new Uint8Array([11,12]).buffer;
                }}});
                this.dispatchEvent(event);
                this.dispatchEvent(new Event('stop'));
            }, 15);
        }
    };
    window.WebSocket = class {
        static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
        constructor(url) { this.url = url; this.readyState = 0; __fake.sockets.push(this); setTimeout(() => { if (this.readyState === 0) { this.readyState = 1; this.onopen?.(); } }, 0); }
        send(frame) {
            if (typeof frame !== 'string') { __fake.frames.push({binary: [...frame]}); return; }
            const data = JSON.parse(frame); __fake.frames.push(data);
            if (data.type === 'stop') setTimeout(() => {
                if (currentMode === 'translation') this.onmessage?.({data:JSON.stringify({type:'translation',translated:'The final phrase.',original:'Last',is_final:true,timestamp:'00:00:09'})});
                if (!__fake.saved) this.onmessage?.({data:JSON.stringify({type:'error',code:'save_failed',message:'Synthetic save failure'})});
                this.onmessage?.({data:JSON.stringify({type:'done',saved:__fake.saved,empty:false,transcription_id:__fake.saved?'501':undefined,download_url:__fake.saved?'/transcriptions/501/download':undefined})});
            }, 20);
        }
        close() { this.readyState = 3; this.onclose?.(); }
    };
    window.__emit = message => __fake.sockets.at(-1).onmessage({data:JSON.stringify(message)});
    Object.defineProperty(window, 'documentPictureInPicture', { configurable: true, value: { requestWindow: async () => {
        const listeners = {};
        const result = { document: document.implementation.createHTMLDocument('Subtitles'), closed: false,
            addEventListener(type, listener) { listeners[type] = listener; },
            close() { if (this.closed) return; this.closed = true; listeners.pagehide?.(); }
        };
        window.__pip = result;
        return result;
    }}});
})();`;

class CDP {
    constructor(socket) {
        this.socket = socket;
        this.nextId = 0;
        this.pending = new Map();
        this.exceptions = [];
        socket.addEventListener('message', event => {
            const message = JSON.parse(event.data);
            if (message.method === 'Runtime.exceptionThrown') this.exceptions.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text);
            if (!message.id) return;
            const pending = this.pending.get(message.id);
            if (!pending) return;
            clearTimeout(pending.timer);
            this.pending.delete(message.id);
            if (message.error) pending.reject(new Error(JSON.stringify(message.error)));
            else pending.resolve(message.result);
        });
    }
    send(method, params = {}) {
        return new Promise((resolve, reject) => {
            const id = ++this.nextId;
            const timer = setTimeout(() => { this.pending.delete(id); reject(new Error('CDP timeout: ' + method)); }, 15000);
            this.pending.set(id, { resolve, reject, timer });
            this.socket.send(JSON.stringify({id,method,params}));
        });
    }
    async evaluate(expression) {
        const result = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true, userGesture: true });
        if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
        return result.result.value;
    }
    async wait(expression, timeout = 7000) {
        const deadline = Date.now() + timeout;
        while (Date.now() < deadline) {
            if (await this.evaluate(expression)) return;
            await delay(35);
        }
        throw new Error('Condition not met: ' + expression);
    }
}

test('workspace tabs, translation lifecycle, persisted preferences and secondary pages', { timeout: 90000 }, async () => {
    let preferences = {...defaults};
    let downloads = 0;
    const settingsUpdates = [];
    const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'transcriber-browser-'));
    const server = createServer(async (request, response) => {
        try {
            const url = new URL(request.url, 'http://localhost');
            response.setHeader('Cache-Control', 'no-store');
            if (url.pathname.startsWith('/user/') || url.pathname === '/transcriptions') {
                response.setHeader('Content-Type', 'application/json');
                if (request.method === 'PUT') {
                    let body = '';
                    for await (const chunk of request) body += chunk;
                    const updates = JSON.parse(body);
                    settingsUpdates.push(updates);
                    preferences = {...preferences, ...updates};
                }
                const user = { id:42,email:'demo@example.test',full_name:'Alex Morgan',auth_provider:'local',created_at:'2026-01-01T00:00:00Z',picture_url:null };
                const profile = { user, settings: preferences };
                const value = url.pathname === '/user/stats/summary' ? { profile, token_stats:{total_deepgram_seconds:125.5,total_deepl_characters:2010,total_requests:12,year:2026} } :
                    url.pathname === '/transcriptions' ? {transcriptions:[{id:501,filename:'translation.txt',content:'<img src=x onerror="window.__xss=true"> A saved translation.',created_at:'2026-11-07T12:00:00Z',orig_language:'EN',translate_to:'RU',file_size:150}],total:1,skip:0,limit:10} :
                    url.pathname === '/user/profile' ? profile : { settings: preferences, updated: true };
                response.end(JSON.stringify(value));
                return;
            }
            if (url.pathname === '/transcriptions/501/download') {
                downloads++;
                response.setHeader('Content-Type', 'text/plain;charset=utf-8');
                response.setHeader('Content-Disposition', 'attachment; filename="translated.txt"');
                response.end(Array.from({length:8},(_,i)=>'Phrase '+(i+1)+'.').concat('The final phrase.').join('\n'));
                return;
            }
            const name = url.pathname === '/' ? 'index.html' : decodeURIComponent(url.pathname.slice(1));
            const filename = path.resolve(root, 'frontend', name);
            if (!filename.startsWith(path.resolve(root, 'frontend') + path.sep)) { response.writeHead(403).end(); return; }
            const types = {'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'};
            response.setHeader('Content-Type', types[path.extname(filename)] || 'application/octet-stream');
            response.end(await fs.readFile(filename));
        } catch { response.writeHead(404).end(); }
    });
    let chrome;
    let cdp;
    try {
        server.listen(0, '127.0.0.1');
        await once(server, 'listening');
        const origin = `http://127.0.0.1:${server.address().port}`;
        const binary = process.env.CHROME_BIN || '/usr/bin/google-chrome-stable';
        chrome = spawn(binary, ['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-first-run','--no-default-browser-check','--disable-background-networking',`--user-data-dir=${path.join(temp,'profile')}`,'--remote-debugging-port=0','about:blank'], {stdio:['ignore','ignore','pipe']});
        const browserAddress = await new Promise((resolve, reject) => {
            let output = '';
            const timer = setTimeout(() => reject(new Error('Chrome did not start. Set CHROME_BIN to the installed Chrome/Chromium binary.')),15000);
            chrome.on('error', error => { clearTimeout(timer); reject(error); });
            chrome.stderr.on('data', chunk => {
                output += chunk.toString();
                const match = output.match(/DevTools listening on (ws:\/\/[^\s]+)/);
                if (match) { clearTimeout(timer); resolve(new URL(match[1])); }
            });
        });
        const targets = await (await fetch(`http://${browserAddress.host}/json/list`)).json();
        const socket = new WebSocket(targets.find(target=>target.type==='page').webSocketDebuggerUrl);
        await new Promise((resolve,reject) => { socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true}); });
        cdp = new CDP(socket);
        await cdp.send('Page.enable');
        await cdp.send('Runtime.enable');
        await cdp.send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
        await cdp.send('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:path.join(temp,'downloads')});
        await cdp.send('Page.addScriptToEvaluateOnNewDocument',{source:browserMocks});
        const navigate = async name => {
            await cdp.send('Page.navigate',{url:origin+name});
            await cdp.wait(`document.readyState === 'complete' && !!window.UI && location.pathname === '${name}'`);
        };
        await navigate('/');
        await cdp.wait(`document.querySelector('#tabTranscriber') && !document.querySelector('#useMic').checked`);
        assert.equal(await cdp.evaluate('document.documentElement.lang'),'en');
        assert.equal(await cdp.evaluate('document.documentElement.dataset.theme'),'dark');
        assert.equal(await cdp.evaluate(`document.querySelector('header').textContent.includes('Web Transcriber')`),false);
        assert.equal(await cdp.evaluate(`document.querySelector('#tabTranscriber').textContent.trim()`),'Transcriber');
        assert.equal(await cdp.evaluate(`document.querySelector('#resultSection').hidden`),false);
        assert.equal(await cdp.evaluate(`__fake.tracks.length`),0,'listing devices must not open a microphone');

        await cdp.evaluate(`document.querySelector('#tabReader').click()`);
        assert.equal(await cdp.evaluate(`document.querySelector('#readerPanel').hidden`),false);
        assert.equal(await cdp.evaluate(`!!document.querySelector('#readerInput')`),true);
        await cdp.evaluate(`document.querySelector('#tabTranslator').click()`);
        assert.equal(await cdp.evaluate(`document.querySelector('#resultSection').hidden`),true);
        await cdp.evaluate(`document.querySelector('#btnStartTranslation').click()`);
        await cdp.wait(`window.__pip?.document.querySelector('[data-share-audio]')`);
        await cdp.evaluate(`__pip.document.querySelector('[data-share-audio]').click()`);
        await cdp.wait(`activeSession && activeSession.recorders.some(recorder=>recorder.state==='recording')`);
        assert.equal(await cdp.evaluate(`document.querySelector('#resultSection').hidden`),true);
        await cdp.evaluate(`for(let i=1;i<=8;i++) __emit({type:'translation',translated:'Phrase '+i+'.',original:'Original '+i,is_final:true,timestamp:'00:00:0'+i}); __emit({type:'translation',translated:'Pending phrase',is_final:false});`);
        assert.equal(await cdp.evaluate(`__pip.document.querySelectorAll('.pip-final-item').length`),6);
        assert.equal(await cdp.evaluate(`modeViews.translation.segments.length`),8);
        await cdp.evaluate(`document.querySelector('#tabTranscriber').click()`);
        assert.equal(await cdp.evaluate(`document.querySelector('#btnStart').disabled`),true);
        await cdp.evaluate(`document.querySelector('#tabTranslator').click(); document.querySelector('#btnStop').click()`);
        await cdp.wait(`!activeSession && modeViews.translation.completed`);
        assert.equal(await cdp.evaluate(`document.querySelector('#resultSection').hidden`),false);
        assert.equal(await cdp.evaluate(`document.querySelectorAll('#transcriptBox .message').length`),9);
        assert.equal(await cdp.evaluate(`document.querySelector('#transcriptBox').textContent.includes('The final phrase.')`),true);
        assert.equal(await cdp.evaluate(`__fake.tracks.every(track=>track.stopped)`),true);
        const frames = await cdp.evaluate(`__fake.frames`);
        assert.equal(frames[0].type,'start_translation');
        assert.equal(frames.at(-2).binary[0],1,'source byte must precede the last WebM chunk');
        assert.equal(frames.at(-1).type,'stop','stop must follow final async dataavailable');
        await cdp.evaluate(`document.querySelector('#downloadLink').click()`);
        await cdp.wait(`true`);
        for (let attempt=0; attempt<60 && !downloads; attempt++) await delay(25);
        assert.equal(downloads,1);
        for (let attempt=0; attempt<60; attempt++) { try { await fs.access(path.join(temp,'downloads/translated.txt')); break; } catch { await delay(25); } }
        assert.match(await fs.readFile(path.join(temp,'downloads/translated.txt'),'utf8'),/Phrase 1\.[\s\S]*The final phrase\./);
        await cdp.evaluate(`document.querySelector('#tabTranscriber').click(); document.querySelector('#tabTranslator').click()`);
        assert.equal(await cdp.evaluate(`document.querySelectorAll('#transcriptBox .message').length`),9,'tab switching preserves the complete translation');

        await cdp.evaluate(`document.querySelector('[data-theme-toggle]').click()`);
        await cdp.wait(`document.documentElement.dataset.theme==='light'`);
        await cdp.send('Page.reload');
        await cdp.wait(`document.readyState==='complete' && document.documentElement.dataset.theme==='light' && !!window.UI`);
        assert.equal(preferences.theme,'light');
        await navigate('/profile.html');
        await cdp.wait(`document.querySelector('#profileContent').style.display !== 'none'`);
        await cdp.evaluate(`const input=document.querySelector('[data-ui-language]'); input.value='ru'; input.dispatchEvent(new Event('change',{bubbles:true}));`);
        await cdp.wait(`document.documentElement.lang==='ru'`);
        assert.equal(await cdp.evaluate(`document.querySelector('[data-theme-toggle]').checked`),false);
        await cdp.evaluate(`document.querySelector('[data-theme-toggle]').click()`);
        await cdp.wait(`document.documentElement.dataset.theme==='dark'`);
        await cdp.evaluate(`document.querySelector('#saveSettingsBtn').click()`);
        await cdp.wait(`document.querySelector('#saveSettingsBtn').disabled === false`);
        for(let attempt=0;attempt<60&&preferences.ui_language!=='ru';attempt++) await delay(25);
        assert.equal(preferences.ui_language,'ru');
        assert.equal(preferences.theme,'dark');
        assert.ok(settingsUpdates.some(update=>update.ui_language==='ru'));
        await navigate('/');
        await cdp.wait(`document.querySelector('#tabTranscriber')?.textContent.trim()==='Транскрибер'`);
        assert.equal(await cdp.evaluate('document.documentElement.dataset.theme'),'dark');
        await cdp.evaluate(`document.querySelector('#tabTranscriber').click(); document.querySelector('#useSystem').checked=false; document.querySelector('#useMic').checked=true; __fake.denied=true; document.querySelector('#btnStart').click()`);
        await cdp.wait(`!activeSession && document.querySelector('#statusBar').classList.contains('error')`);
        assert.equal(await cdp.evaluate(`document.querySelector('#btnStart').disabled`),false);
        assert.equal(await cdp.evaluate(`document.querySelector('#statusBar').textContent.includes('workspace.')`),false);
        await cdp.evaluate(`__fake.denied=false; document.querySelector('#btnStart').click()`);
        await cdp.wait(`activeSession && activeSession.recorders.some(recorder=>recorder.state==='recording')`);
        await cdp.evaluate(`__emit({type:'transcript',text:'<img src=x onerror="window.__xss=true">',speaker:'me',is_final:true,timestamp:'00:00:01'});`);
        assert.equal(await cdp.evaluate(`document.querySelector('#transcriptBox img')===null && !window.__xss`),true);
        await cdp.evaluate(`activeSession.recorders[0].stop(); document.querySelector('#btnStop').click()`);
        await cdp.wait(`!activeSession`);
        assert.equal(await cdp.evaluate(`__fake.frames.at(-2).binary[0]`),0,'an already inactive recorder still sends its last chunk before stop');

        await navigate('/transcriptions.html');
        await cdp.wait(`document.querySelector('#transcriptionsList').textContent.includes('A saved translation.')`);
        assert.equal(await cdp.evaluate(`!window.__xss && !document.querySelector('#transcriptionsList img')`),true);
        await navigate('/edit_profile.html');
        await cdp.wait(`document.querySelector('#fullName')?.value==='Alex Morgan'`);
        await cdp.evaluate(`UI.setLanguage('en')`);
        await navigate('/');
        await cdp.wait(`document.querySelector('#tabTranslator')?.textContent.trim()==='Translator'`);
        // A failed save still exposes a complete, downloadable local result.
        await cdp.evaluate(`__fake.saved=false; document.querySelector('#tabTranslator').click(); document.querySelector('#btnStartTranslation').click()`);
        await cdp.wait(`window.__pip?.document.querySelector('[data-share-audio]')`);
        await cdp.evaluate(`__pip.document.querySelector('[data-share-audio]').click()`);
        await cdp.wait(`activeSession && activeSession.recorders.some(recorder=>recorder.state==='recording')`);
        await cdp.evaluate(`__emit({type:'translation',translated:'Keep this local copy.',is_final:true}); document.querySelector('#btnStop').click()`);
        await cdp.wait(`!activeSession && modeViews.translation.completed`);
        assert.equal(await cdp.evaluate(`!!modeViews.translation.download.local`),true);
        assert.equal(await cdp.evaluate(`document.querySelector('#statusBar').classList.contains('error')`),true);
        await cdp.evaluate(`document.querySelector('#downloadLink').click()`);
        await delay(100);
        assert.equal(downloads,1,'local fallback must not request a nonexistent server document');

        await cdp.send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
        assert.equal(await cdp.evaluate(`document.documentElement.scrollWidth <= window.innerWidth`),true,'mobile workspace must not overflow');
        await cdp.send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
        await cdp.evaluate(`document.querySelector('#tabTranscriber').click()`);
        const screenshot = await cdp.send('Page.captureScreenshot',{format:'png'});
        await fs.writeFile('/tmp/web-transcriber-dark.png',Buffer.from(screenshot.data,'base64'));
        await cdp.evaluate(`UI.setTheme('light')`);
        const lightScreenshot = await cdp.send('Page.captureScreenshot',{format:'png'});
        await fs.writeFile('/tmp/web-transcriber-light.png',Buffer.from(lightScreenshot.data,'base64'));
        await cdp.evaluate(`localStorage.removeItem('access_token');localStorage.removeItem('refresh_token');`);
        await navigate('/login.html');
        assert.equal(await cdp.evaluate(`document.querySelector('label[for=password]').textContent.trim()`),'Password');
        await navigate('/register.html');
        assert.equal(await cdp.evaluate(`document.documentElement.lang`),'en');
        assert.deepEqual(cdp.exceptions,[],'no uncaught browser errors');
    } finally {
        cdp?.socket.close();
        if (chrome) { chrome.kill('SIGTERM'); await Promise.race([once(chrome,'exit'),delay(2000)]); }
        await new Promise(resolve=>server.close(resolve));
        await fs.rm(temp,{recursive:true,force:true,maxRetries:5,retryDelay:100});
    }
});
