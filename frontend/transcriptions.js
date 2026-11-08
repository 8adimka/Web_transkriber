/* Saved transcripts and translations. All server content is rendered as text. */
(function () {
    'use strict';
    const byId = id => document.getElementById(id);
    const t = (key, variables) => window.UI.t(key, variables);
    const itemsPerPage = 10;
    let currentPage = 1;
    let totalItems = 0;
    let texts = [];
    let selectedId = null;
    let previousFocus = null;
    let requestVersion = 0;

    function node(tag, className, text) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text !== undefined) element.textContent = text;
        return element;
    }
    async function tokenRequest(path, options = {}) {
        function url() {
            const parsed = new URL(path, window.location.origin);
            parsed.searchParams.set('token', window.auth.getAccessToken());
            return parsed.pathname + parsed.search;
        }
        let response = await fetch(url(), options);
        if (response.status === 401) {
            const renewed = await window.auth.refreshAccessToken();
            if (!renewed) throw new Error('Session unavailable');
            response = await fetch(url(), options);
        }
        if (response.status === 401) {
            window.auth.logout();
            throw new Error('Session unavailable');
        }
        return response;
    }
    function formatDate(value) {
        return new Date(value).toLocaleString(window.UI.locale, {
            year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit'
        });
    }
    function formatSize(value) {
        const amount = Number(value) || 0;
        const units = amount < 1024 ? [amount, 'bytes'] : amount < 1048576 ? [amount / 1024, 'kilobytes'] : [amount / 1048576, 'megabytes'];
        return units[0].toLocaleString(window.UI.locale, { maximumFractionDigits: 1 }) + ' ' + t('saved.' + units[1]);
    }
    function renderTexts() {
        const list = byId('transcriptionsList');
        list.replaceChildren();
        if (!texts.length) {
            const empty = node('div', 'empty-state');
            empty.append(node('h2', '', t('saved.empty')), node('p', '', t('saved.emptyHint')));
            const link = node('a', 'button secondary', t('saved.create'));
            link.href = 'index.html';
            empty.append(link);
            list.append(empty);
            return;
        }
        for (const text of texts) {
            const article = node('article', 'transcription-item');
            article.dataset.id = String(text.id);
            const header = node('div', 'transcription-header');
            const title = node('div', 'transcription-title');
            const filename = String(text.filename || '');
            const audioFilename = /^(dialog|transcription)_/i.test(filename);
            title.append(node('h2', '', !filename || audioFilename ? formatDate(text.created_at) : filename));
            const metadata = String(text.orig_language || '') + (text.translate_to ? ' → ' + String(text.translate_to) : '') + (text.file_size ? ' · ' + formatSize(text.file_size) : '');
            title.append(node('span', 'transcription-meta', metadata));
            const actions = node('div', 'transcription-actions');
            const download = node('button', 'button small secondary', t('common.download'));
            download.type = 'button';
            download.addEventListener('click', () => downloadText(text.id, download));
            const open = node('a', 'button small secondary', t('reader.open'));
            open.href = 'index.html?reader=' + encodeURIComponent(text.id);
            const remove = node('button', 'button small danger', t('common.delete'));
            remove.type = 'button';
            remove.addEventListener('click', () => showDeleteModal(text.id));
            actions.append(open, download, remove);
            header.append(title, actions);
            const content = String(text.content || '');
            article.append(header, node('p', 'transcription-preview', content.length > 240 ? content.slice(0, 240) + '…' : content));
            list.append(article);
        }
    }
    function renderPagination() {
        const pagination = byId('pagination');
        pagination.replaceChildren();
        if (totalItems <= itemsPerPage) return;
        const pages = Math.ceil(totalItems / itemsPerPage);
        const controls = node('div', 'pagination-controls');
        const previous = node('button', 'button small secondary', t('saved.previous'));
        previous.type = 'button'; previous.disabled = currentPage === 1;
        previous.addEventListener('click', () => loadTexts(currentPage - 1));
        const next = node('button', 'button small secondary', t('saved.next'));
        next.type = 'button'; next.disabled = currentPage === pages;
        next.addEventListener('click', () => loadTexts(currentPage + 1));
        controls.append(previous, node('span', 'page-info', t('saved.page', { page: currentPage, pages })), next);
        pagination.append(controls);
    }
    function updateInfo() {
        delete byId('transcriptionsInfo').dataset.i18n;
        byId('transcriptionsInfo').textContent = totalItems
            ? t('saved.count', { start: (currentPage - 1) * itemsPerPage + 1, end: Math.min(currentPage * itemsPerPage, totalItems), total: totalItems })
            : t('saved.none');
    }
    function render() { renderTexts(); renderPagination(); updateInfo(); }
    function showError(key) {
        const error = node('div', 'error', t(key));
        error.setAttribute('role', 'alert');
        error.dataset.i18n = key;
        byId('transcriptionsList').replaceChildren(error);
    }
    async function loadTexts(page = 1) {
        const version = ++requestVersion;
        byId('transcriptionsList').setAttribute('aria-busy', 'true');
        try {
            const response = await tokenRequest('/transcriptions?skip=' + ((page - 1) * itemsPerPage) + '&limit=' + itemsPerPage + '&preview_chars=300');
            if (!response.ok) throw new Error('Texts unavailable');
            const data = await response.json();
            if (version !== requestVersion) return;
            texts = data.transcriptions;
            totalItems = Number(data.total);
            currentPage = page;
            if (currentPage > 1 && !texts.length && totalItems) {
                await loadTexts(Math.ceil(totalItems / itemsPerPage));
                return;
            }
            if (!totalItems) currentPage = 1;
            render();
        } catch (_) { if (version === requestVersion) showError('saved.loadError'); }
        finally { if (version === requestVersion) byId('transcriptionsList').setAttribute('aria-busy', 'false'); }
    }
    async function downloadText(id, button) {
        button.disabled = true;
        try {
            const response = await tokenRequest('/transcriptions/' + encodeURIComponent(id) + '/download');
            if (!response.ok) throw new Error('Download unavailable');
            const disposition = response.headers.get('Content-Disposition') || '';
            const match = disposition.match(/filename="([^"]+)"/) || disposition.match(/filename=([^;]+)/);
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const link = node('a');
            link.href = url;
            link.download = match ? match[1].trim() : 'text_' + id + '.txt';
            document.body.append(link);
            link.click(); link.remove();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
        } catch (_) { alert(t('saved.downloadError')); }
        finally { button.disabled = false; }
    }
    function closeDeleteModal() {
        byId('deleteModal').style.display = 'none';
        selectedId = null;
        previousFocus?.focus();
    }
    function showDeleteModal(id) {
        selectedId = id;
        previousFocus = document.activeElement;
        byId('deleteModal').style.display = 'flex';
        byId('cancelDelete').focus();
    }
    async function deleteText() {
        if (selectedId === null) return;
        byId('confirmDelete').disabled = true;
        try {
            const response = await tokenRequest('/transcriptions/' + encodeURIComponent(selectedId), { method: 'DELETE' });
            if (!response.ok) throw new Error('Delete unavailable');
            closeDeleteModal();
            await loadTexts(currentPage);
        } catch (_) { alert(t('saved.deleteError')); }
        finally { byId('confirmDelete').disabled = false; }
    }
    document.addEventListener('DOMContentLoaded', () => {
        if (!window.auth.isAuthenticated()) { window.location.href = 'login.html'; return; }
        byId('cancelDelete').addEventListener('click', closeDeleteModal);
        byId('confirmDelete').addEventListener('click', deleteText);
        byId('deleteModal').addEventListener('click', event => { if (event.target === byId('deleteModal')) closeDeleteModal(); });
        byId('deleteModal').addEventListener('keydown', event => {
            if (event.key === 'Escape') { event.preventDefault(); closeDeleteModal(); }
            if (event.key === 'Tab') {
                const first = byId('cancelDelete'); const last = byId('confirmDelete');
                if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
                else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
            }
        });
        loadTexts();
    });
    document.addEventListener('ui:change', () => {
        // Keep existing error/loading state while updating already loaded content.
        if (byId('transcriptionsList').querySelector('.transcription-item, .empty-state')) render();
    });
})();
