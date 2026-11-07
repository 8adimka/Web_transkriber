/* Account settings and localized usage statistics. */
(function () {
    'use strict';
    let profileData = null;
    const byId = id => document.getElementById(id);
    const t = (key, variables) => window.UI.t(key, variables);

    async function request(url, options = {}) {
        const response = await window.auth.authFetch(url, options);
        if (!response) throw new Error('Session unavailable');
        return response;
    }
    function setStatus(key, error = false) {
        const element = byId(error ? 'error' : 'settingsStatus');
        element.dataset.i18n = key;
        element.textContent = t(key);
        element.style.display = 'block';
        if (error) byId('loading').style.display = 'none';
    }
    function renderIdentity() {
        if (!profileData) return;
        const { user } = profileData.profile;
        const stats = profileData.token_stats;
        byId('userFullName').textContent = user.full_name || user.email;
        byId('userEmail').textContent = user.email;
        const registered = new Date(user.created_at);
        byId('userSince').textContent = t('profile.joined', { date: registered.toLocaleDateString(window.UI.locale) });
        byId('deepgramSeconds').textContent = Number(stats.total_deepgram_seconds || 0).toLocaleString(window.UI.locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
        byId('deeplCharacters').textContent = Number(stats.total_deepl_characters || 0).toLocaleString(window.UI.locale);
        byId('totalRequests').textContent = Number(stats.total_requests || 0).toLocaleString(window.UI.locale);
        byId('statsYear').textContent = stats.year;
    }
    async function loadProfile() {
        const revision = window.UI.preferenceRevision;
        try {
            const response = await request('/user/stats/summary');
            if (!response.ok) throw new Error('Profile unavailable');
            profileData = await response.json();
            const { user, settings } = profileData.profile;
            window.UI.applyPreferences(settings, revision);
            const avatar = byId('userAvatar');
            avatar.onerror = () => { avatar.onerror = null; avatar.src = 'avatar-placeholder.svg'; };
            avatar.src = user.picture_url || settings.avatar_url || 'avatar-placeholder.svg';
            byId('microphoneEnabled').checked = settings.microphone_enabled;
            byId('tabAudioEnabled').checked = settings.tab_audio_enabled;
            byId('originalLanguage').value = settings.original_language;
            byId('translationLanguage').value = settings.translation_language;
            renderIdentity();
            byId('loading').style.display = 'none';
            byId('profileContent').style.display = 'block';
        } catch (_) { setStatus('profile.loadError', true); }
    }
    async function saveSettings() {
        const revision = window.UI.preferenceRevision;
        const button = byId('saveSettingsBtn');
        button.disabled = true;
        byId('error').style.display = 'none';
        const settings = {
            microphone_enabled: byId('microphoneEnabled').checked,
            tab_audio_enabled: byId('tabAudioEnabled').checked,
            original_language: byId('originalLanguage').value,
            translation_language: byId('translationLanguage').value,
            ui_language: window.UI.language,
            theme: window.UI.theme
        };
        try {
            const response = await request('/user/settings', {
                method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(settings)
            });
            if (!response.ok) throw new Error('Settings unavailable');
            const result = await response.json();
            localStorage.setItem('user_settings', JSON.stringify(result.settings));
            if (profileData) profileData.profile.settings = result.settings;
            window.UI.applyPreferences(result.settings, revision);
            setStatus('profile.saved');
        } catch (_) { setStatus('profile.saveError', true); }
        finally { button.disabled = false; }
    }
    function resetSettings() {
        if (!confirm(t('profile.resetConfirm'))) return;
        byId('microphoneEnabled').checked = true;
        byId('tabAudioEnabled').checked = true;
        byId('originalLanguage').value = 'RU';
        byId('translationLanguage').value = 'EN';
        window.UI.setLanguage('en', false);
        window.UI.setTheme('dark', false);
        saveSettings();
    }
    document.addEventListener('DOMContentLoaded', () => {
        if (!window.auth.isAuthenticated()) { window.location.href = 'login.html'; return; }
        byId('saveSettingsBtn').addEventListener('click', saveSettings);
        byId('resetSettingsBtn').addEventListener('click', resetSettings);
        byId('editProfileBtn').addEventListener('click', () => { window.location.href = 'edit_profile.html'; });
        loadProfile();
    });
    document.addEventListener('ui:change', renderIdentity);
})();
