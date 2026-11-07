/* Personal information and password settings. */
(function () {
    'use strict';
    const byId = id => document.getElementById(id);
    const t = (key, variables) => window.UI.t(key, variables);
    let registrationDate = null;

    async function request(url, options = {}) {
        const response = await window.auth.authFetch(url, options);
        if (!response) throw new Error('Session unavailable');
        return response;
    }
    function message(key, success = false) {
        const element = byId(success ? 'success' : 'error');
        element.dataset.i18n = key;
        element.textContent = t(key);
        element.style.display = 'block';
        byId(success ? 'error' : 'success').style.display = 'none';
    }
    function renderDate() {
        if (registrationDate) byId('createdAt').value = registrationDate.toLocaleDateString(window.UI.locale);
    }
    function updateAvatarPreview() {
        const value = byId('avatarUrl').value.trim();
        const image = byId('currentAvatar');
        image.onerror = () => { image.onerror = null; image.src = 'avatar-placeholder.svg'; };
        if (!value) { image.src = 'avatar-placeholder.svg'; return; }
        try {
            const url = new URL(value);
            image.src = ['http:', 'https:'].includes(url.protocol) ? url.href : 'avatar-placeholder.svg';
        } catch (_) { image.src = 'avatar-placeholder.svg'; }
    }
    async function loadProfile() {
        const revision = window.UI.preferenceRevision;
        try {
            const response = await request('/user/stats/summary');
            if (!response.ok) throw new Error('Profile unavailable');
            const { profile } = await response.json();
            window.UI.applyPreferences(profile.settings, revision);
            byId('fullName').value = profile.user.full_name || '';
            byId('email').value = profile.user.email;
            byId('avatarUrl').value = profile.user.picture_url || profile.settings.avatar_url || '';
            registrationDate = new Date(profile.user.created_at);
            renderDate();
            updateAvatarPreview();
            byId('loading').style.display = 'none';
            byId('profileContent').style.display = 'block';
        } catch (_) {
            byId('loading').style.display = 'none';
            message('profile.loadError');
        }
    }
    async function saveProfile() {
        const avatarUrl = byId('avatarUrl').value.trim();
        const fullName = byId('fullName').value.trim();
        if (avatarUrl && (!/^https?:\/\//i.test(avatarUrl) || !byId('avatarUrl').checkValidity())) { message('profile.avatarInvalid'); return; }
        byId('saveProfileBtn').disabled = true;
        try {
            const response = await request('/user/profile', {
                method: 'PUT', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ full_name: fullName, picture_url: avatarUrl || null })
            });
            if (!response.ok) throw new Error('Profile unavailable');
            const settingsResponse = await request('/user/settings', {
                method: 'PUT', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ avatar_url: avatarUrl || null })
            });
            if (!settingsResponse.ok) throw new Error('Settings unavailable');
            const cached = window.auth.getUserInfo() || {};
            localStorage.setItem('user_info', JSON.stringify({ ...cached, full_name: fullName, picture_url: avatarUrl || null }));
            message('profile.updated', true);
            setTimeout(() => { window.location.href = 'profile.html'; }, 1000);
        } catch (_) { message('profile.updateError'); }
        finally { byId('saveProfileBtn').disabled = false; }
    }
    function checkPasswordStrength() {
        const password = byId('newPassword').value;
        const element = byId('passwordStrength');
        if (!password) { element.textContent = ''; delete element.dataset.i18n; return; }
        const score = Number(password.length >= 8) + Number(password.length >= 12)
            + Number(/[a-z]/.test(password)) + Number(/[A-Z]/.test(password))
            + Number(/[0-9]/.test(password)) + Number(/[^a-zA-Z0-9]/.test(password));
        const strength = score <= 2 ? 'weak' : score <= 4 ? 'medium' : 'strong';
        element.dataset.i18n = 'password.' + strength;
        element.textContent = t('password.' + strength);
        element.className = 'password-strength strength-' + strength;
    }
    async function changePassword() {
        const currentPassword = byId('currentPassword').value;
        const newPassword = byId('newPassword').value;
        if (!currentPassword) { message('password.enterCurrent'); return; }
        if (!newPassword) { message('password.enterNew'); return; }
        if (newPassword !== byId('confirmPassword').value) { message('password.mismatch'); return; }
        if (newPassword.length < 8) { message('password.minimum'); return; }
        byId('changePasswordBtn').disabled = true;
        try {
            const response = await request('/user/change-password', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ current_password: currentPassword, new_password: newPassword })
            });
            if (response.status === 401) { message('password.incorrect'); return; }
            if (!response.ok) throw new Error('Password unavailable');
            ['currentPassword', 'newPassword', 'confirmPassword'].forEach(id => { byId(id).value = ''; });
            checkPasswordStrength();
            message('password.changed', true);
        } catch (_) { message('password.error'); }
        finally { byId('changePasswordBtn').disabled = false; }
    }
    document.addEventListener('DOMContentLoaded', () => {
        if (!window.auth.isAuthenticated()) { window.location.href = 'login.html'; return; }
        byId('saveProfileBtn').addEventListener('click', saveProfile);
        byId('changePasswordBtn').addEventListener('click', changePassword);
        byId('cancelBtn').addEventListener('click', () => { if (confirm(t('profile.cancelConfirm'))) window.location.href = 'profile.html'; });
        byId('uploadAvatarBtn').addEventListener('click', () => alert(t('profile.avatarUploadLater')));
        byId('removeAvatarBtn').addEventListener('click', () => {
            if (confirm(t('profile.removeAvatarConfirm'))) { byId('avatarUrl').value = ''; updateAvatarPreview(); }
        });
        byId('avatarUrl').addEventListener('input', updateAvatarPreview);
        byId('newPassword').addEventListener('input', checkPasswordStrength);
        loadProfile();
    });
    document.addEventListener('ui:change', renderDate);
})();
