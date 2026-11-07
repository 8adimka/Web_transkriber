/* Run with: node --test tests/test_ui_preferences.cjs */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup({ stored = {}, authenticated = false, saveFails = false } = {}) {
    const storage = new Map(Object.entries(stored));
    if (authenticated) storage.set('access_token', 'synthetic-test-token');
    const requests = [];
    const events = [];
    const switches = [{ checked: false }, { checked: false }];
    const selects = [{ value: '' }];
    const elements = new Map();
    const document = {
        documentElement: { lang: '', dataset: {} },
        querySelectorAll(selector) {
            if (selector === '[data-theme-toggle]') return switches;
            if (selector === '[data-ui-language]') return selects;
            return [];
        },
        addEventListener() {},
        dispatchEvent(event) { events.push(event); },
        getElementById(id) { return elements.get(id); },
        createElement() {
            return { dataset: {}, setAttribute() {}, hidden: true };
        },
        body: { appendChild(element) { elements.set(element.id, element); } }
    };
    const context = {
        document,
        window: { addEventListener() {} },
        localStorage: { getItem(key) { return storage.get(key) || null; }, setItem(key, value) { storage.set(key, value); } },
        CustomEvent: class { constructor(type, options) { this.type = type; Object.assign(this, options); } },
        fetch: async (url, options) => {
            requests.push({ url, patch: JSON.parse(options.body) });
            if (saveFails) throw new Error('synthetic network failure');
            return { ok: true };
        },
        console
    };
    vm.createContext(context);
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../frontend/ui.js'), 'utf8'), context);
    return { ui: context.window.UI, document, storage, requests, events, switches, selects, elements };
}

test('a new browser starts in English and dark mode', () => {
    const state = setup();
    assert.equal(state.ui.language, 'en');
    assert.equal(state.ui.theme, 'dark');
    assert.equal(state.document.documentElement.lang, 'en');
    assert.equal(state.document.documentElement.dataset.theme, 'dark');
    assert.equal(state.ui.t('nav.saved'), 'Saved texts');
});

test('language and theme persist locally and synchronize all controls', async () => {
    const state = setup();
    await state.ui.setLanguage('ru');
    await state.ui.setTheme('light');
    assert.equal(state.ui.t('nav.saved'), 'Сохранённые тексты');
    assert.equal(state.ui.locale, 'ru-RU');
    assert.equal(state.ui.t('common.error', { message: '<synthetic>' }), 'Ошибка: <synthetic>');
    assert.ok(state.switches.every(input => input.checked === false));
    assert.equal(state.selects[0].value, 'ru');
    assert.equal(state.requests.length, 0);
    const reloaded = setup({ stored: Object.fromEntries(state.storage) });
    assert.equal(reloaded.ui.theme, 'light');
    assert.equal(reloaded.ui.language, 'ru');
});

test('hydrating account settings does not write them back to the server', () => {
    const state = setup({ authenticated: true });
    state.ui.applyPreferences({ ui_language: 'ru', theme: 'light' });
    assert.equal(state.ui.language, 'ru');
    assert.equal(state.ui.theme, 'light');
    assert.equal(state.requests.length, 0);
    assert.equal(state.events.at(-1).type, 'ui:change');
});

test('authenticated changes send partial preference patches without overwriting audio settings', async () => {
    const state = setup({ authenticated: true, stored: { user_settings: JSON.stringify({ microphone_enabled: false, original_language: 'ES' }) } });
    await Promise.all([state.ui.setTheme('light'), state.ui.setLanguage('ru')]);
    assert.deepEqual(state.requests.map(request => request.patch), [{ theme: 'light' }, { ui_language: 'ru' }]);
    const cached = JSON.parse(state.storage.get('user_settings'));
    assert.equal(cached.microphone_enabled, false);
    assert.equal(cached.original_language, 'ES');
    assert.equal(cached.ui_language, 'ru');
    assert.equal(cached.theme, 'light');
});

test('failed account sync preserves the local choice and shows an accessible notice', async () => {
    const state = setup({ authenticated: true, saveFails: true });
    assert.equal(await state.ui.setTheme('light'), false);
    assert.equal(state.ui.theme, 'light');
    assert.equal(JSON.parse(state.storage.get('ui_preferences')).theme, 'light');
    assert.equal(state.elements.get('uiSyncNotice').hidden, false);
    assert.match(state.elements.get('uiSyncNotice').textContent, /saved on this device/);
});

test('all declared interface translation keys have English and Russian text', async () => {
    const { ui } = setup();
    const frontend = path.join(__dirname, '../frontend');
    const files = fs.readdirSync(frontend).filter(name => /\.(html|js)$/.test(name) && name !== 'ui.js');
    const keys = new Set();
    for (const name of files) {
        const source = fs.readFileSync(path.join(frontend, name), 'utf8');
        for (const match of source.matchAll(/data-i18n(?:-placeholder|-title|-aria-label|-alt)?="([^"]+)"/g)) keys.add(match[1]);
        for (const match of source.matchAll(/(?:UI\.t|\bt)\(['"]([a-z]+\.[a-zA-Z]+)['"]/g)) keys.add(match[1]);
    }
    for (const language of ['en', 'ru']) {
        await ui.setLanguage(language, false);
        for (const key of keys) assert.notEqual(ui.t(key), key, `Missing ${language} translation: ${key}`);
    }
});


test('a delayed old settings GET cannot undo a newer successfully saved preference', async () => {
    const state = setup({ authenticated: true });
    const getRevision = state.ui.preferenceRevision;
    let completeOldGet;
    const oldGet = new Promise(resolve => { completeOldGet = resolve; });
    const applyOldGet = oldGet.then(settings => state.ui.applyPreferences(settings, getRevision));
    await state.ui.setTheme('light');
    assert.equal(state.requests.length, 1); // The PUT is already complete, not merely pending.
    assert.equal(state.ui.preferenceRevision, getRevision + 1);
    completeOldGet({ theme: 'dark', ui_language: 'ru' });
    await applyOldGet;
    assert.equal(state.ui.theme, 'light');
    assert.equal(state.ui.language, 'en');
    assert.equal(state.document.documentElement.dataset.theme, 'light');
    assert.equal(JSON.parse(state.storage.get('user_settings')).theme, 'light');
    assert.equal(state.ui.preferenceRevision, getRevision + 1); // Hydration itself is not a user change.
});

test('a response at the current preference revision applies account settings', () => {
    const state = setup();
    state.ui.applyPreferences({ theme: 'light', ui_language: 'ru' }, state.ui.preferenceRevision);
    assert.equal(state.ui.theme, 'light');
    assert.equal(state.ui.language, 'ru');
    assert.equal(state.ui.preferenceRevision, 0);
});

test('message placeholders retranslate known authentication errors on language changes', async () => {
    const state = setup();
    const variables = { message: state.ui.t('Ошибка входа') };
    assert.equal(state.ui.t('common.error', variables), 'Error: Could not log in');
    await state.ui.setLanguage('ru', false);
    assert.equal(state.ui.t('common.error', variables), 'Ошибка: Ошибка входа');
});
