/* A reflowable, account-backed Reader. Documents are rendered only as text. */
(function () {
    'use strict';
    const $ = id => document.getElementById(id);
    const t = (key, values = {}) => window.UI.t(key, values);
    const base = '/api/transcriber/reader';
    const maxFileSize = 10 * 1024 * 1024;
    const maxTextLength = 5000000;
    const supported = /\.(txt|text|fb2|epub|docx|pdf|md|markdown|html|htm)$/i;
    const state = {
        visible: false, initialized: false, document: null, position: 0, page: 0,
        starts: [0], paginating: false, fontSize: 20, pending: null, saving: false,
        generation: 0, layout: 0, signature: '', saveStatus: null, importStatus: null,
        progress: null, progressClock: 0, focus: false
    };
    let measure;
    let resizeTimer;
    let selectionTimer;
    let progressTimer;
    let translationAbort;
    let translationVersion = 0;
    let currentTranslationKey = '';
    let anchorRectangle;
    let pointerInPage = false;
    let progressQueue = Promise.resolve();
    let localDB;
    const translations = new Map();
    const book = $('readerBook');
    const page = $('readerPage');
    const frame = $('readerPageFrame');
    const popover = $('readerPopover');
    const input = $('readerInput');
    const sessionOwner = String(window.auth.getUserInfo()?.id || 'unknown');
    const owner = () => sessionOwner;
    const sameAccount = () => window.auth.isAuthenticated() && String(window.auth.getUserInfo()?.id || 'unknown') === sessionOwner;
    function requireAccount() {
        if (sameAccount()) return;
        state.generation++; state.layout++;
        state.document = null; state.pending = null;
        page.replaceChildren(); input.value = '';
        book.hidden = true; $('readerImport').hidden = false;
        hideTranslation();
        status('reader.accountChanged', true, 'import');
        const error = new Error('Account changed');
        error.code = 'account_changed';
        throw error;
    }
    const progressKey = id => 'reader_progress:' + owner() + ':' + id;
    const nextFrame = () => new Promise(resolve => requestAnimationFrame(resolve));

    function status(key, error = false, area = 'save') {
        state[area === 'save' ? 'saveStatus' : 'importStatus'] = { key, error };
        const element = $(area === 'save' ? 'readerSaveStatus' : 'readerImportStatus');
        element.textContent = key ? t(key) : '';
        element.classList.toggle('error', error);
    }
    function errorKey(error, fallback) {
        return ({
            account_changed: 'reader.accountChanged', unsupported_format: 'reader.unsupportedFormat', file_too_large: 'reader.tooLarge',
            text_too_large: 'reader.tooLarge', too_large: 'reader.tooLarge', invalid_document: 'reader.invalidDocument',
            unsafe_document: 'reader.invalidDocument', encrypted_document: 'reader.encryptedDocument',
            empty_document: 'reader.noText', no_text_layer: 'reader.noText',
            unsupported_encoding: 'reader.invalidDocument', translation_unavailable: 'reader.translateUnavailable',
            missing_translation_key: 'reader.translateUnavailable', rate_limited: 'reader.rateLimited',
            translation_quota_exceeded: 'reader.rateLimited', translation_limit: 'reader.rateLimited', document_not_found: 'reader.loadError'
        })[error.code] || fallback;
    }
    async function request(path, options = {}) {
        requireAccount();
        const controller = new AbortController();
        const abort = () => controller.abort();
        if (options.signal?.aborted) controller.abort();
        else options.signal?.addEventListener('abort', abort, { once: true });
        const timer = setTimeout(abort, 30000);
        try {
            const response = await window.auth.authFetch(base + path, { ...options, signal: controller.signal });
            if (!response) throw new Error('Session unavailable');
            const body = await response.json().catch(() => ({}));
            requireAccount();
            if (!response.ok) {
                const error = new Error('Reader request failed');
                error.status = response.status;
                error.code = body.detail?.code || (response.status === 429 ? 'rate_limited' : 'request_failed');
                throw error;
            }
            return body;
        } finally {
            clearTimeout(timer);
            options.signal?.removeEventListener('abort', abort);
        }
    }
    function jsonOptions(method, body) {
        return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
    }
    function languages() { return { source_lang: $('sourceLang').value, target_lang: $('targetLang').value }; }
    function uuid() {
        if (crypto.randomUUID) return crypto.randomUUID();
        const bytes = crypto.getRandomValues(new Uint8Array(16));
        bytes[6] = (bytes[6] & 15) | 64;
        bytes[8] = (bytes[8] & 63) | 128;
        const value = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
        return `${value.slice(0, 8)}-${value.slice(8, 12)}-${value.slice(12, 16)}-${value.slice(16, 20)}-${value.slice(20)}`;
    }
    function setURL(id) {
        const url = new URL(location.href);
        if (state.visible) url.searchParams.set('mode', 'reader');
        else url.searchParams.delete('mode');
        if (id && state.visible) url.searchParams.set('reader', String(id));
        else url.searchParams.delete('reader');
        history.replaceState(null, '', url.pathname + url.search + url.hash);
    }
    function readLocalProgress(id) {
        try { return JSON.parse(localStorage.getItem(progressKey(id)) || 'null'); } catch { return null; }
    }
    function rememberProgress(progress, pending) {
        try { localStorage.setItem(progressKey(progress.id), JSON.stringify({ ...progress, pending })); } catch { /* account saving still works */ }
    }
    function database() {
        if (!localDB) localDB = new Promise((resolve, reject) => {
            const opening = indexedDB.open('web-transcriber-reader', 1);
            opening.onupgradeneeded = () => opening.result.createObjectStore('pending', { keyPath: 'owner' });
            opening.onsuccess = () => resolve(opening.result);
            opening.onerror = () => reject(opening.error);
        });
        return localDB;
    }
    async function storeDraft(draft) {
        try {
            const db = await database();
            await new Promise((resolve, reject) => {
                const transaction = db.transaction('pending', 'readwrite');
                transaction.objectStore('pending').put({ owner: owner(), draft });
                transaction.oncomplete = resolve;
                transaction.onerror = () => reject(transaction.error);
            });
        } catch { /* a server save is still attempted if browser storage is full */ }
    }
    async function restoreDraft() {
        try {
            const db = await database();
            return await new Promise((resolve, reject) => {
                const read = db.transaction('pending').objectStore('pending').get(owner());
                read.onsuccess = () => resolve(read.result?.draft || null);
                read.onerror = () => reject(read.error);
            });
        } catch { return null; }
    }
    async function removeDraft(clientId) {
        try {
            const db = await database();
            const transaction = db.transaction('pending', 'readwrite');
            const store = transaction.objectStore('pending');
            const read = store.get(owner());
            read.onsuccess = () => { if (read.result?.draft?.client_id === clientId) store.delete(owner()); };
        } catch { /* retaining a successful idempotent draft is harmless */ }
    }
    function busy() {
        $('readerRead').disabled = state.saving;
        $('readerChooseFile').disabled = state.saving;
        $('readerNew').disabled = !!state.pending;
        $('readerRetry').hidden = (!state.pending && !(state.progress && state.saveStatus?.error)) || state.saving;
        $('readerRetryImport').hidden = !state.pending || state.saving;
        $('readerImport').setAttribute('aria-busy', String(state.saving));
    }
    function titleFor(text) {
        const first = text.split('\n', 1)[0] || t('reader.untitled');
        return Array.from(first.trim().slice(0, 240)).slice(0, 120).join('');
    }
    function showDocument(document, position) {
        hideTranslation();
        state.layout++;
        state.document = document;
        const local = document.id ? readLocalProgress(document.id) : null;
        const useLocal = local?.pending && local.updated_at_ms > (document.progress_updated_at_ms || 0);
        const anchor = position ?? (useLocal ? local.position : document.position || 0);
        state.position = Math.max(0, Math.min(document.content.length, anchor));
        state.progressClock = Math.max(state.progressClock, document.progress_updated_at_ms || 0, local?.updated_at_ms || 0);
        state.page = 0;
        state.starts = [0];
        state.signature = '';
        $('readerTitle').removeAttribute('data-i18n');
        $('readerTitle').textContent = document.title || t('reader.untitled');
        $('readerImport').hidden = true;
        book.hidden = false;
        setURL(document.id);
        if (state.visible) scheduleLayout();
        if (useLocal) {
            state.progress = { ...local, id: document.id };
            flushProgress();
        }
    }
    async function savePending() {
        const draft = state.pending;
        if (!draft || state.saving) return;
        state.saving = true;
        busy();
        status(draft.kind === 'file' ? 'reader.importing' : 'reader.saving', false, book.hidden ? 'import' : 'save');
        await storeDraft(draft);
        try {
            const document = draft.kind === 'file'
                ? await request('/import?' + new URLSearchParams(draft.languages), {
                    method: 'POST', headers: {
                        'Content-Type': 'application/octet-stream', 'X-File-Name': encodeURIComponent(draft.filename),
                        'Idempotency-Key': draft.client_id
                    }, body: draft.file
                })
                : await request('/documents', jsonOptions('POST', {
                    title: draft.title, content: draft.content, client_id: draft.client_id, ...draft.languages
                }));
            if (state.pending !== draft) return;
            state.pending = null;
            const anchor = draft.kind === 'text' ? state.position : document.position;
            showDocument(document, anchor);
            status('reader.saved');
            status('', false, 'import');
            removeDraft(draft.client_id);
            // Reading may have started while the new text was being saved.
            queueProgress();
        } catch (error) {
            // A malformed/unsupported document cannot succeed by retrying it.
            // Keep its error visible, but allow the next import and avoid a reload loop.
            if ([409, 413, 415, 422].includes(error.status) && state.pending === draft) {
                state.pending = null;
                await removeDraft(draft.client_id);
            }
            status(errorKey(error, 'reader.saveFailed'), true, book.hidden ? 'import' : 'save');
        } finally {
            state.saving = false;
            busy();
        }
    }
    async function importText(value) {
        if (!sameAccount()) { try { requireAccount(); } catch { return; } }
        if (state.pending || state.saving) return;
        const content = String(value).replace(/\r\n?/g, '\n').replace(/^\uFEFF/, '').trim();
        if (!content) { status('reader.emptyText', true, 'import'); return; }
        let characters = 0;
        if (content.length > maxTextLength) for (const character of content) { if (++characters > maxTextLength) break; }
        if (characters > maxTextLength) { status('reader.tooLarge', true, 'import'); return; }
        flushProgress();
        state.generation++;
        const draft = { kind: 'text', client_id: uuid(), title: titleFor(content), content, languages: languages() };
        state.pending = draft;
        showDocument({ id: null, title: draft.title, content, position: 0 }, 0);
        savePending();
    }
    async function importFile(file) {
        if (!sameAccount()) { try { requireAccount(); } catch { return; } }
        if (!file || state.pending || state.saving) return;
        if (!supported.test(file.name)) { status('reader.unsupportedFormat', true, book.hidden ? 'import' : 'save'); return; }
        if (file.size > maxFileSize) { status('reader.tooLarge', true, book.hidden ? 'import' : 'save'); return; }
        flushProgress();
        state.generation++;
        state.pending = { kind: 'file', client_id: uuid(), filename: file.name, file, languages: languages() };
        savePending();
    }
    async function loadDocument(id) {
        const generation = ++state.generation;
        status('reader.loading', false, 'import');
        try {
            const document = await request('/documents/' + encodeURIComponent(id));
            if (generation !== state.generation) return;
            showDocument(document);
            status('reader.saved');
            status('', false, 'import');
        } catch (error) { if (generation === state.generation) status(errorKey(error, 'reader.loadError'), true, 'import'); }
    }
    function fitHeight() {
        const viewport = window.visualViewport?.height || innerHeight;
        const navigation = book.querySelector('.reader-pagination');
        const outside = parseFloat(getComputedStyle(document.querySelector('.workspace-container')).paddingBottom) + 28;
        let height = Math.floor(viewport - frame.getBoundingClientRect().top - navigation.getBoundingClientRect().height - outside - 20);
        if (height < 130 && !state.focus) {
            state.focus = true;
            document.body.classList.add('reader-focus');
            refreshFocusLabel();
            height = Math.floor(viewport - frame.getBoundingClientRect().top - navigation.getBoundingClientRect().height - outside - 20);
        }
        frame.style.height = Math.max(90, height) + 'px';
    }
    function prepareMeasure() {
        if (!measure) {
            measure = document.createElement('div');
            measure.className = 'reader-page reader-measure';
            measure.setAttribute('aria-hidden', 'true');
            document.body.appendChild(measure);
        }
        const computed = getComputedStyle(page);
        for (const key of ['fontFamily', 'fontWeight', 'fontStyle', 'lineHeight', 'letterSpacing', 'wordSpacing', 'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'whiteSpace', 'overflowWrap', 'wordBreak', 'boxSizing']) measure.style[key] = computed[key];
        measure.style.fontSize = state.fontSize + 'px';
        measure.style.width = page.getBoundingClientRect().width + 'px';
        measure.style.height = 'auto';
        measure.style.minHeight = '0';
        measure.style.maxHeight = 'none';
        measure.style.overflow = 'visible';
    }
    function pageEnd(text, start) {
        const available = page.clientHeight - 1;
        const fits = end => {
            measure.textContent = text.slice(start, end);
            return measure.getBoundingClientRect().height <= available;
        };
        let low = start;
        let high = Math.min(text.length, start + 3000);
        while (high < text.length && fits(high)) { low = high; high = Math.min(text.length, start + (high - start) * 2); }
        if (fits(high)) return high;
        while (low + 1 < high) {
            const middle = Math.floor((low + high) / 2);
            if (fits(middle)) low = middle; else high = middle;
        }
        let end = Math.max(start + 1, low);
        // Prefer a complete word, while allowing a very long unbroken token to wrap.
        const tail = text.slice(Math.max(start, end - 120), end);
        const whitespace = [...tail.matchAll(/\s+/g)].at(-1);
        if (whitespace && end - (tail.length - whitespace.index - whitespace[0].length) > start) {
            end -= tail.length - whitespace.index - whitespace[0].length;
        }
        if (end < text.length && /[\uD800-\uDBFF]/.test(text[end - 1])) end--;
        return Math.max(start + 1, end);
    }
    function pageAt(position) {
        let low = 0;
        let high = state.starts.length - 1;
        while (low < high) {
            const middle = Math.ceil((low + high) / 2);
            if (state.starts[middle] <= position) low = middle; else high = middle - 1;
        }
        return Math.min(low, Math.max(0, state.starts.length - 2));
    }
    function scheduleLayout() {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(paginate, 65);
    }
    async function paginate() {
        if (!state.visible || !state.document || book.hidden) return;
        book.style.setProperty('--reader-font-size', state.fontSize + 'px');
        fitHeight();
        await nextFrame();
        const signature = [state.generation, page.clientWidth, page.clientHeight, state.fontSize].join(':');
        if (state.signature === signature) return;
        state.signature = signature;
        const layout = ++state.layout;
        const text = state.document.content;
        const anchor = state.position;
        state.paginating = true;
        state.starts = [0];
        prepareMeasure();
        let rendered = false;
        let sliceStart = performance.now();
        while (state.starts.at(-1) < text.length) {
            const end = pageEnd(text, state.starts.at(-1));
            state.starts.push(end);
            if (!rendered && end > anchor) {
                state.page = pageAt(anchor);
                renderPage();
                rendered = true;
            }
            if (performance.now() - sliceStart > 12) {
                updateNavigation();
                await nextFrame();
                if (layout !== state.layout || !state.visible) return;
                sliceStart = performance.now();
            }
        }
        if (layout !== state.layout || !state.visible) return;
        state.paginating = false;
        if (!rendered) state.page = pageAt(anchor);
        renderPage();
        measure.textContent = '';
    }
    function renderPage() {
        if (!state.document) return;
        const start = state.starts[state.page] || 0;
        const end = state.starts[state.page + 1] ?? state.document.content.length;
        const text = state.document.content.slice(start, end);
        const fragment = document.createDocumentFragment();
        const locale = $('sourceLang').value.toLowerCase();
        const parts = typeof Intl.Segmenter === 'function'
            ? new Intl.Segmenter(locale, { granularity: 'word' }).segment(text)
            : [...text.matchAll(/[\p{L}\p{N}\p{M}]+(?:['’\-][\p{L}\p{N}\p{M}]+)*|[^\p{L}\p{N}\p{M}]+/gu)].map(match => ({ segment: match[0], index: match.index, isWordLike: /[\p{L}\p{N}]/u.test(match[0]) }));
        for (const part of parts) {
            if (part.isWordLike) {
                const word = document.createElement('span');
                word.className = 'reader-word';
                word.dataset.offset = String(start + part.index);
                word.textContent = part.segment;
                fragment.appendChild(word);
            } else fragment.appendChild(document.createTextNode(part.segment));
        }
        page.replaceChildren(fragment);
        page.setAttribute('lang', locale);
        updateNavigation();
    }
    function updateNavigation() {
        const total = Math.max(1, state.starts.length - 1);
        $('readerPageNumber').value = state.page + 1;
        $('readerPageNumber').max = total;
        $('readerPageNumber').disabled = state.paginating;
        $('readerPageTotal').textContent = state.paginating ? '…' : String(total);
        for (const id of ['readerFirst', 'readerPrevious', 'readerSidePrevious']) $(id).disabled = state.page === 0;
        for (const id of ['readerNext', 'readerSideNext']) $(id).disabled = state.page + 1 >= total;
        $('readerLast').disabled = state.paginating || state.page + 1 >= total;
        $('readerFontSize').textContent = state.fontSize;
        $('readerFontDecrease').disabled = state.fontSize <= 16;
        $('readerFontIncrease').disabled = state.fontSize >= 28;
        page.setAttribute('aria-busy', String(state.paginating));
    }
    function goToPage(value) {
        if (!state.document) return;
        const total = Math.max(1, state.starts.length - 1);
        const number = Math.min(total, Math.max(1, Math.floor(Number(value) || 1)));
        state.page = number - 1;
        state.position = state.starts[state.page];
        hideTranslation();
        renderPage();
        queueProgress();
    }
    function queueProgress() {
        if (!state.document?.id) {
            if (state.pending?.kind === 'text') {
                state.pending.position = state.position;
                state.pending.page = state.page + 1;
                storeDraft(state.pending);
            }
            return;
        }
        state.progressClock = Math.max(Date.now(), state.progressClock + 1);
        state.progress = {
            id: state.document.id, position: state.position, page: state.page + 1,
            updated_at_ms: state.progressClock
        };
        rememberProgress(state.progress, true);
        clearTimeout(progressTimer);
        progressTimer = setTimeout(flushProgress, 350);
    }
    function flushProgress() {
        clearTimeout(progressTimer);
        const progress = state.progress;
        if (!progress) return progressQueue;
        state.progress = null;
        progressQueue = progressQueue.catch(() => {}).then(async () => {
            try {
                await request('/documents/' + progress.id + '/progress', jsonOptions('PATCH', progress));
                const local = readLocalProgress(progress.id);
                if (local?.updated_at_ms === progress.updated_at_ms) rememberProgress(progress, false);
                if (state.progress?.id === progress.id && state.progress.updated_at_ms <= progress.updated_at_ms) state.progress = null;
                if (state.document?.id === progress.id && !state.pending && (!local || local.updated_at_ms <= progress.updated_at_ms)) status('reader.saved');
                busy();
            } catch {
                if (state.document?.id === progress.id) {
                    if (!state.progress || state.progress.updated_at_ms < progress.updated_at_ms) state.progress = progress;
                    status('reader.saveFailed', true); busy();
                }
            }
        });
        return progressQueue;
    }
    function hideTranslation() {
        clearTimeout(selectionTimer);
        translationVersion++;
        translationAbort?.abort();
        translationAbort = null;
        currentTranslationKey = '';
        popover.hidden = true;
    }
    function positionPopover() {
        if (!anchorRectangle || popover.hidden) return;
        const rectangle = popover.getBoundingClientRect();
        const width = document.documentElement.clientWidth;
        const height = window.visualViewport?.height || innerHeight;
        const left = Math.max(8, Math.min(width - rectangle.width - 8, anchorRectangle.left));
        let top = anchorRectangle.bottom + 10;
        if (top + rectangle.height > height - 8) top = Math.max(8, anchorRectangle.top - rectangle.height - 10);
        popover.style.left = left + 'px';
        popover.style.top = top + 'px';
    }
    async function translate(text, rectangle) {
        clearTimeout(selectionTimer);
        text = text.trim().replace(/\s+/g, ' ');
        if (!text) return;
        const lang = languages();
        const key = JSON.stringify([lang.source_lang, lang.target_lang, text]);
        if (key === currentTranslationKey && !popover.hidden) return;
        hideTranslation();
        currentTranslationKey = key;
        const version = ++translationVersion;
        anchorRectangle = { left: rectangle.left, top: rectangle.top, bottom: rectangle.bottom };
        $('readerPopoverSource').textContent = text;
        $('readerPopoverText').textContent = '';
        $('readerPopoverStatus').classList.remove('error');
        $('readerPopoverStatus').textContent = t('reader.translating');
        popover.hidden = false;
        positionPopover();
        if (Array.from(text).length > 5000) {
            $('readerPopoverStatus').textContent = t('reader.selectTooLong');
            $('readerPopoverStatus').classList.add('error');
            positionPopover();
            return;
        }
        if (translations.has(key)) {
            $('readerPopoverText').textContent = translations.get(key);
            $('readerPopoverStatus').textContent = '';
            positionPopover();
            return;
        }
        translationAbort = new AbortController();
        try {
            const result = await request('/translate', { ...jsonOptions('POST', { text, ...lang }), signal: translationAbort.signal });
            if (version !== translationVersion) return;
            const translated = String(result.translated || '');
            translations.set(key, translated);
            if (translations.size > 150) translations.delete(translations.keys().next().value);
            $('readerPopoverText').textContent = translated;
            $('readerPopoverStatus').textContent = '';
            positionPopover();
        } catch (error) {
            if (version !== translationVersion) return;
            $('readerPopoverStatus').textContent = t(errorKey(error, 'reader.translateError'));
            $('readerPopoverStatus').classList.add('error');
            positionPopover();
        }
    }
    function selectedPhrase() {
        const selection = window.getSelection();
        if (!selection || selection.isCollapsed || !selection.rangeCount ||
            !page.contains(selection.anchorNode) || !page.contains(selection.focusNode)) return null;
        const range = selection.getRangeAt(0);
        const rectangles = range.getClientRects();
        return { text: selection.toString(), rectangle: rectangles[rectangles.length - 1] || range.getBoundingClientRect() };
    }
    function translateSelection() {
        const selected = selectedPhrase();
        if (selected) translate(selected.text, selected.rectangle);
    }
    function refreshFocusLabel() {
        const key = state.focus ? 'reader.exitFocus' : 'reader.focus';
        $('readerFocus').textContent = t(key);
        $('readerFocus').setAttribute('aria-pressed', String(state.focus));
        $('readerFocus').removeAttribute('data-i18n');
    }
    function setFontSize(size) {
        state.fontSize = Math.max(16, Math.min(28, size));
        try { localStorage.setItem('reader_font_size:' + owner(), String(state.fontSize)); } catch { /* optional preference */ }
        hideTranslation();
        state.signature = '';
        scheduleLayout();
    }
    function newText() {
        if (state.pending) return;
        flushProgress();
        state.generation++;
        state.layout++;
        state.document = null;
        state.focus = false;
        document.body.classList.remove('reader-focus');
        book.hidden = true;
        $('readerImport').hidden = false;
        input.value = '';
        $('readerFile').value = '';
        hideTranslation();
        status('', false, 'import');
        setURL(null);
        input.focus();
    }
    async function onActivate() {
        state.visible = true;
        document.body.classList.add('reader-active');
        if (!state.initialized) {
            state.initialized = true;
            try { state.fontSize = Math.max(16, Math.min(28, Number(localStorage.getItem('reader_font_size:' + owner())) || 20)); } catch { /* default */ }
            const requested = new URL(location.href).searchParams.get('reader');
            if (requested && /^\d+$/.test(requested)) { await loadDocument(requested); return; }
            const draft = await restoreDraft();
            if (draft && !state.document && !state.pending) {
                state.pending = draft;
                if (draft.kind === 'text') showDocument({ id: null, title: draft.title, content: draft.content }, draft.position || 0);
                savePending();
            }
        }
        setURL(state.document?.id);
        if (state.document) scheduleLayout();
    }
    function onDeactivate() {
        state.visible = false;
        state.layout++;
        state.signature = '';
        state.focus = false;
        document.body.classList.remove('reader-active', 'reader-focus');
        hideTranslation();
        flushProgress();
        setURL(null);
    }
    for (const [id, place] of [['readerRetry', book.querySelector('.reader-book-actions')], ['readerRetryImport', $('readerImport')]]) {
        const button = document.createElement('button');
        button.id = id;
        button.type = 'button';
        button.className = 'button secondary small';
        button.dataset.i18n = 'common.retry';
        button.textContent = t('common.retry');
        button.hidden = true;
        button.addEventListener('click', () => state.pending ? savePending() : flushProgress());
        place.appendChild(button);
    }
    $('readerRead').addEventListener('click', () => importText(input.value));
    $('readerChooseFile').addEventListener('click', () => $('readerFile').click());
    $('readerFile').addEventListener('change', event => importFile(event.target.files[0]));
    input.addEventListener('paste', event => {
        const files = event.clipboardData?.files;
        if (files?.length) { event.preventDefault(); importFile(files[0]); return; }
        const text = event.clipboardData?.getData('text/plain');
        if (text) { event.preventDefault(); input.value = text; importText(text); }
    });
    input.addEventListener('input', event => { if (event.inputType === 'insertFromPaste' && input.value.trim()) importText(input.value); });
    let dragDepth = 0;
    const dropZone = $('readerPanel');
    dropZone.addEventListener('dragenter', event => { event.preventDefault(); dragDepth++; $('readerImport').classList.add('drag-over'); });
    dropZone.addEventListener('dragover', event => { event.preventDefault(); if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'; });
    dropZone.addEventListener('dragleave', () => { if (--dragDepth <= 0) { dragDepth = 0; $('readerImport').classList.remove('drag-over'); } });
    dropZone.addEventListener('drop', event => {
        event.preventDefault(); dragDepth = 0; $('readerImport').classList.remove('drag-over');
        if (event.dataTransfer?.files.length) importFile(event.dataTransfer.files[0]);
        else { const text = event.dataTransfer?.getData('text/plain'); if (text) importText(text); }
    });
    $('readerNew').addEventListener('click', newText);
    $('readerFirst').addEventListener('click', () => goToPage(1));
    $('readerLast').addEventListener('click', () => goToPage(state.starts.length - 1));
    for (const id of ['readerPrevious', 'readerSidePrevious']) $(id).addEventListener('click', () => goToPage(state.page));
    for (const id of ['readerNext', 'readerSideNext']) $(id).addEventListener('click', () => goToPage(state.page + 2));
    $('readerPageNumber').addEventListener('change', event => goToPage(event.target.value));
    $('readerPageNumber').addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); goToPage(event.target.value); page.focus(); } });
    $('readerFontDecrease').addEventListener('click', () => setFontSize(state.fontSize - 2));
    $('readerFontIncrease').addEventListener('click', () => setFontSize(state.fontSize + 2));
    $('readerFocus').addEventListener('click', () => {
        state.focus = !state.focus;
        document.body.classList.toggle('reader-focus', state.focus);
        refreshFocusLabel(); hideTranslation(); state.signature = ''; scheduleLayout();
    });
    $('readerPopoverClose').addEventListener('click', hideTranslation);
    document.addEventListener('pointerdown', event => {
        pointerInPage = page.contains(event.target);
        if (!popover.contains(event.target)) hideTranslation();
    });
    page.addEventListener('pointerup', () => { clearTimeout(selectionTimer); translateSelection(); });
    page.addEventListener('mouseup', () => { clearTimeout(selectionTimer); translateSelection(); });
    page.addEventListener('click', event => {
        const selected = selectedPhrase();
        if (selected) { translate(selected.text, selected.rectangle); return; }
        const word = event.target.closest('.reader-word');
        if (word) translate(word.textContent, word.getBoundingClientRect());
    });
    document.addEventListener('selectionchange', () => {
        if (!state.visible || !pointerInPage || !selectedPhrase()) return;
        clearTimeout(selectionTimer);
        selectionTimer = setTimeout(translateSelection, 280);
    });
    page.addEventListener('keyup', translateSelection);
    document.addEventListener('keydown', event => {
        if (!state.visible || !state.document) return;
        if (event.key === 'Escape') {
            if (!popover.hidden) hideTranslation();
            else if (state.focus) { state.focus = false; document.body.classList.remove('reader-focus'); refreshFocusLabel(); state.signature = ''; scheduleLayout(); }
            return;
        }
        if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey ||
            event.target.closest('input, textarea, button, a, select, #readerPopover') || !window.getSelection().isCollapsed) return;
        const places = { ArrowLeft: state.page, PageUp: state.page, ArrowRight: state.page + 2, PageDown: state.page + 2, Home: 1, End: state.starts.length - 1 };
        if (event.key in places && !state.paginating) { event.preventDefault(); goToPage(places[event.key]); }
    });
    for (const id of ['sourceLang', 'targetLang']) $(id).addEventListener('change', () => { translations.clear(); hideTranslation(); });
    document.addEventListener('ui:change', () => {
        for (const area of ['save', 'import']) {
            const current = state[area === 'save' ? 'saveStatus' : 'importStatus'];
            if (current) status(current.key, current.error, area);
        }
        refreshFocusLabel(); hideTranslation(); scheduleLayout();
    });
    new ResizeObserver(() => { if (state.visible && state.document) scheduleLayout(); }).observe(frame);
    window.addEventListener('resize', () => { hideTranslation(); scheduleLayout(); });
    window.visualViewport?.addEventListener('resize', () => { hideTranslation(); scheduleLayout(); });
    window.addEventListener('online', () => { if (state.pending) savePending(); else flushProgress(); });
    window.addEventListener('storage', event => {
        if (['user_info', 'access_token', 'refresh_token'].includes(event.key) && !sameAccount()) location.reload();
    });
    window.addEventListener('pagehide', () => {
        if (!sameAccount()) return;
        const progress = state.progress || (state.document?.id ? readLocalProgress(state.document.id) : null);
        if (!progress?.pending && !state.progress) return;
        if (!progress?.id) return;
        rememberProgress(progress, true);
        fetch(base + '/documents/' + progress.id + '/progress', {
            ...jsonOptions('PATCH', progress), keepalive: true,
            headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + window.auth.getAccessToken() }
        }).catch(() => {});
    });
    window.Reader = {
        onActivate, onDeactivate, loadDocument, importText, importFile, goToPage,
        get state() { return { documentId: state.document?.id, page: state.page + 1, totalPages: Math.max(1, state.starts.length - 1), position: state.position, fontSize: state.fontSize, paginating: state.paginating, visible: state.visible }; }
    };
    busy();
})();
