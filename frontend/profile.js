// profile.js - Логика страницы профиля пользователя

document.addEventListener('DOMContentLoaded', function () {
    // Проверка авторизации
    checkAuth();

    // Загрузка профиля
    loadProfile();

    // Настройка обработчиков событий
    document.getElementById('saveSettingsBtn').addEventListener('click', saveSettings);
    document.getElementById('resetSettingsBtn').addEventListener('click', resetSettings);
    document.getElementById('logoutBtn').addEventListener('click', logout);
    document.getElementById('editProfileBtn').addEventListener('click', editProfile);
});

// Проверка авторизации
function checkAuth() {
    const token = localStorage.getItem('access_token');
    if (!token) {
        window.location.href = 'login.html';
        return;
    }

    // Обновляем информацию о пользователе в шапке
    const userInfo = JSON.parse(localStorage.getItem('user_info') || '{}');
    const userNameElement = document.getElementById('userName');
    if (userNameElement && userInfo.email) {
        userNameElement.textContent = userInfo.email;
    }

    // Показываем блок с информацией о пользователе
    const userInfoDiv = document.getElementById('userInfo');
    const loginPromptDiv = document.getElementById('loginPrompt');
    if (userInfoDiv && loginPromptDiv) {
        userInfoDiv.style.display = 'block';
        loginPromptDiv.style.display = 'none';
    }
}

// Загрузка профиля пользователя
async function loadProfile() {
    const token = localStorage.getItem('access_token');
    if (!token) return;

    try {
        // Загружаем профиль и статистику
        const response = await fetch('/user/stats/summary', {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });

        if (!response.ok) {
            if (response.status === 401) {
                // Токен невалидный, разлогиниваем
                localStorage.removeItem('access_token');
                localStorage.removeItem('user_info');
                window.location.href = 'login.html';
                return;
            }
            throw new Error(`Ошибка загрузки профиля: ${response.status}`);
        }

        const data = await response.json();

        // Обновляем UI
        updateProfileUI(data);

        // Скрываем загрузку, показываем контент
        document.getElementById('loading').style.display = 'none';
        document.getElementById('profileContent').style.display = 'block';

    } catch (error) {
        console.error('Ошибка загрузки профиля:', error);
        showError(`Не удалось загрузить профиль: ${error.message}`);
    }
}

// Обновление UI профиля
function updateProfileUI(data) {
    const { profile, token_stats } = data;

    // Информация о пользователе
    const user = profile.user;
    const settings = profile.settings;

    // Аватар
    const avatarUrl = user.picture_url || settings.avatar_url;
    if (avatarUrl) {
        const avatarElement = document.getElementById('userAvatar');
        avatarElement.src = avatarUrl;
        // Добавляем обработчик ошибок загрузки
        avatarElement.onerror = function () {
            console.warn('Не удалось загрузить аватар:', avatarUrl);
            // Пробуем использовать placeholder
            this.src = 'https://via.placeholder.com/100';
        };
    } else {
        // Если нет аватара, используем placeholder
        document.getElementById('userAvatar').src = 'https://via.placeholder.com/100';
    }

    // Имя и email
    document.getElementById('userFullName').textContent = user.full_name || user.email;
    document.getElementById('userEmail').textContent = user.email;

    // Дата регистрации
    const regDate = new Date(user.created_at);
    document.getElementById('userSince').textContent = `Зарегистрирован: ${regDate.toLocaleDateString('ru-RU')}`;

    // Статистика токенов
    document.getElementById('deepgramSeconds').textContent = token_stats.total_deepgram_seconds.toFixed(1);
    document.getElementById('deeplCharacters').textContent = token_stats.total_deepl_characters.toLocaleString('ru-RU');
    document.getElementById('totalRequests').textContent = token_stats.total_requests.toLocaleString('ru-RU');
    document.getElementById('statsYear').textContent = token_stats.year;

    // Настройки
    document.getElementById('microphoneEnabled').checked = settings.microphone_enabled;
    document.getElementById('tabAudioEnabled').checked = settings.tab_audio_enabled;
    document.getElementById('originalLanguage').value = settings.original_language;
    document.getElementById('translationLanguage').value = settings.translation_language;
}

// Сохранение настроек
async function saveSettings() {
    const token = localStorage.getItem('access_token');
    if (!token) return;

    const settings = {
        microphone_enabled: document.getElementById('microphoneEnabled').checked,
        tab_audio_enabled: document.getElementById('tabAudioEnabled').checked,
        original_language: document.getElementById('originalLanguage').value,
        translation_language: document.getElementById('translationLanguage').value
    };

    try {
        const response = await fetch('/user/settings', {
            method: 'PUT',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(settings)
        });

        if (!response.ok) {
            throw new Error(`Ошибка сохранения настроек: ${response.status}`);
        }

        const result = await response.json();

        // Показываем уведомление об успехе
        alert('Настройки успешно сохранены!');

        // Обновляем профиль
        loadProfile();

    } catch (error) {
        console.error('Ошибка сохранения настроек:', error);
        showError(`Не удалось сохранить настройки: ${error.message}`);
    }
}

// Сброс настроек к умолчаниям
function resetSettings() {
    if (confirm('Вы уверены, что хотите сбросить настройки к значениям по умолчанию?')) {
        document.getElementById('microphoneEnabled').checked = true;
        document.getElementById('tabAudioEnabled').checked = true;
        document.getElementById('originalLanguage').value = 'RU';
        document.getElementById('translationLanguage').value = 'EN';

        // Автоматически сохраняем
        saveSettings();
    }
}

// Редактирование профиля
function editProfile() {
    window.location.href = 'edit_profile.html';
}

// Смена аватара
function changeAvatar() {
    alert('Функция смены аватара будет реализована в будущем');
}

// Смена пароля
function changePassword() {
    const oldPassword = prompt('Введите старый пароль:');
    if (oldPassword === null) return;

    const newPassword = prompt('Введите новый пароль:');
    if (newPassword === null) return;

    const confirmPassword = prompt('Повторите новый пароль:');
    if (confirmPassword === null) return;

    if (newPassword !== confirmPassword) {
        alert('Пароли не совпадают');
        return;
    }

    alert('Функция смены пароля будет реализована в будущем');
}

// Показ ошибки
function showError(message) {
    const errorDiv = document.getElementById('error');
    errorDiv.textContent = message;
    errorDiv.style.display = 'block';

    // Скрываем загрузку
    document.getElementById('loading').style.display = 'none';
}

// Выход из системы
function logout() {
    localStorage.removeItem('access_token');
    localStorage.removeItem('user_info');
    localStorage.removeItem('user_settings');
    window.location.href = 'login.html';
}