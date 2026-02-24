// Утилиты для работы с токенами
const TOKEN_KEY = 'access_token';
const REFRESH_TOKEN_KEY = 'refresh_token';
const USER_INFO_KEY = 'user_info';
const USER_SETTINGS_KEY = 'user_settings';

// Базовый URL для API запросов
const API_BASE_URL = window.location.protocol === 'https:' ? 'https://localhost' : 'http://localhost:8000';

// Сохранение токенов
function saveTokens(accessToken, refreshToken, userInfo) {
    localStorage.setItem(TOKEN_KEY, accessToken);
    localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
    localStorage.setItem(USER_INFO_KEY, JSON.stringify(userInfo));
}

// Получение токенов
function getAccessToken() {
    return localStorage.getItem(TOKEN_KEY);
}

function getRefreshToken() {
    return localStorage.getItem(REFRESH_TOKEN_KEY);
}

function getUserInfo() {
    const info = localStorage.getItem(USER_INFO_KEY);
    return info ? JSON.parse(info) : null;
}

// Проверка авторизации
function isAuthenticated() {
    return !!getAccessToken();
}

// Выход
function logout() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    localStorage.removeItem(USER_INFO_KEY);
    localStorage.removeItem(USER_SETTINGS_KEY);
    window.location.href = 'login.html';
}

// Обновление токена
async function refreshAccessToken() {
    const refreshToken = getRefreshToken();
    if (!refreshToken) {
        logout();
        return null;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/auth/refresh/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ refresh_token: refreshToken }),
        });

        if (!response.ok) {
            throw new Error('Refresh failed');
        }

        const data = await response.json();
        saveTokens(data.access_token, data.refresh_token, {
            id: data.id,
            email: data.email,
            full_name: data.full_name,
            picture_url: data.picture_url,
            auth_provider: data.auth_provider,
        });
        return data.access_token;
    } catch (error) {
        console.error('Token refresh failed:', error);
        logout();
        return null;
    }
}

// Запрос с автоматическим обновлением токена
async function authFetch(url, options = {}) {
    let token = getAccessToken();
    if (!token) {
        window.location.href = 'login.html';
        return;
    }

    const headers = {
        ...options.headers,
        'Authorization': `Bearer ${token}`,
    };

    let response = await fetch(url, { ...options, headers });

    // Если токен истек, пробуем обновить
    if (response.status === 401) {
        const newToken = await refreshAccessToken();
        if (newToken) {
            headers['Authorization'] = `Bearer ${newToken}`;
            response = await fetch(url, { ...options, headers });
        } else {
            logout();
            return;
        }
    }

    return response;
}

// Обновление UI пользователя (кликабельное имя и аватар)
function updateUserUI() {
    const userInfo = getUserInfo();
    const userNameElement = document.getElementById('userName');
    const userInfoDiv = document.getElementById('userInfo');
    const loginPromptDiv = document.getElementById('loginPrompt');
    const userAvatarSmall = document.getElementById('userAvatarSmall');

    if (userInfo && userNameElement && userInfoDiv && loginPromptDiv) {
        // Обновляем имя пользователя
        userNameElement.textContent = userInfo.full_name || userInfo.email;

        // Обновляем аватар
        if (userAvatarSmall) {
            const avatarUrl = userInfo.picture_url;
            if (avatarUrl) {
                userAvatarSmall.src = avatarUrl;
                userAvatarSmall.onerror = function () {
                    console.warn('Не удалось загрузить аватар:', avatarUrl);
                    this.src = 'https://via.placeholder.com/40';
                };
            } else {
                userAvatarSmall.src = 'https://via.placeholder.com/40';
            }
        }

        // Показываем блок пользователя
        userInfoDiv.style.display = 'flex';
        loginPromptDiv.style.display = 'none';

        // Добавляем обработчик выхода
        const logoutBtn = document.getElementById('logoutBtn');
        if (logoutBtn) {
            logoutBtn.addEventListener('click', logout);
        }
    } else if (loginPromptDiv) {
        // Показываем блок входа
        if (userInfoDiv) userInfoDiv.style.display = 'none';
        loginPromptDiv.style.display = 'block';
    }
}

// Загрузка настроек пользователя
async function loadUserSettings() {
    const token = getAccessToken();
    if (!token) return null;

    try {
        const response = await fetch(`${API_BASE_URL}/user/settings`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });

        if (response.ok) {
            const data = await response.json();
            localStorage.setItem(USER_SETTINGS_KEY, JSON.stringify(data.settings));
            return data.settings;
        }
    } catch (error) {
        console.error('Ошибка загрузки настроек:', error);
    }

    return null;
}

// Получение сохраненных настроек
function getUserSettings() {
    const settings = localStorage.getItem(USER_SETTINGS_KEY);
    return settings ? JSON.parse(settings) : null;
}

// Применение настроек к главной странице
function applyUserSettings() {
    const settings = getUserSettings();
    if (!settings) return;

    // Применяем настройки к элементам на главной странице
    const useMicCheckbox = document.getElementById('useMic');
    const useSystemCheckbox = document.getElementById('useSystem');
    const sourceLangSelect = document.getElementById('sourceLang');
    const targetLangSelect = document.getElementById('targetLang');

    if (useMicCheckbox) useMicCheckbox.checked = settings.microphone_enabled;
    if (useSystemCheckbox) useSystemCheckbox.checked = settings.tab_audio_enabled;
    if (sourceLangSelect) sourceLangSelect.value = settings.original_language;
    if (targetLangSelect) targetLangSelect.value = settings.translation_language;
}

// Сохранение настроек при изменении на главной странице
function setupSettingsAutoSave() {
    const useMicCheckbox = document.getElementById('useMic');
    const useSystemCheckbox = document.getElementById('useSystem');
    const sourceLangSelect = document.getElementById('sourceLang');
    const targetLangSelect = document.getElementById('targetLang');

    if (!useMicCheckbox || !useSystemCheckbox || !sourceLangSelect || !targetLangSelect) {
        return;
    }

    const saveSettings = debounce(async () => {
        const token = getAccessToken();
        if (!token) return;

        const settings = {
            microphone_enabled: useMicCheckbox.checked,
            tab_audio_enabled: useSystemCheckbox.checked,
            original_language: sourceLangSelect.value,
            translation_language: targetLangSelect.value
        };

        try {
            const response = await fetch(`${API_BASE_URL}/user/settings`, {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(settings)
            });

            if (!response.ok) {
                throw new Error(`Ошибка сохранения: ${response.status}`);
            }

            // Обновляем локальные настройки
            localStorage.setItem(USER_SETTINGS_KEY, JSON.stringify(settings));
            console.log('Настройки сохранены:', settings);
        } catch (error) {
            console.error('Ошибка сохранения настроек:', error);
        }
    }, 1000);

    // Добавляем обработчики
    useMicCheckbox.addEventListener('change', saveSettings);
    useSystemCheckbox.addEventListener('change', saveSettings);
    sourceLangSelect.addEventListener('change', saveSettings);
    targetLangSelect.addEventListener('change', saveSettings);
}

// Синхронизация настроек из Redis при загрузке страницы
async function syncSettingsFromRedis() {
    const token = getAccessToken();
    if (!token) return;

    try {
        const response = await fetch(`${API_BASE_URL}/user/settings/redis/sync`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });

        if (response.ok) {
            console.log('Настройки синхронизированы из Redis');
        }
    } catch (error) {
        console.error('Ошибка синхронизации настроек из Redis:', error);
    }
}

// Вспомогательная функция debounce
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Обработка формы входа
if (document.getElementById('loginForm')) {
    const loginForm = document.getElementById('loginForm');
    const statusEl = document.getElementById('authStatus');

    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = new FormData(loginForm);
        const data = {
            username: formData.get('email'),
            password: formData.get('password'),
        };

        statusEl.textContent = 'Вход...';
        statusEl.className = 'status-bar';

        try {
            const response = await fetch(`${API_BASE_URL}/auth/token/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: new URLSearchParams(data),
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Ошибка входа');
            }

            const result = await response.json();
            saveTokens(result.access_token, result.refresh_token, {
                id: result.id,
                email: result.email,
                full_name: result.full_name,
                picture_url: result.picture_url,
                auth_provider: result.auth_provider,
            });

            // Загружаем настройки пользователя
            await loadUserSettings();

            statusEl.textContent = 'Успешный вход! Перенаправление...';
            statusEl.className = 'status-bar success';
            setTimeout(() => {
                window.location.href = 'index.html';
            }, 1000);
        } catch (error) {
            statusEl.textContent = `Ошибка: ${error.message}`;
            statusEl.className = 'status-bar error';
        }
    });
}

// Обработка формы регистрации
if (document.getElementById('registerForm')) {
    const registerForm = document.getElementById('registerForm');
    const statusEl = document.getElementById('authStatus');

    registerForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = new FormData(registerForm);
        const password = formData.get('password');
        const confirmPassword = formData.get('confirmPassword');

        if (password !== confirmPassword) {
            statusEl.textContent = 'Пароли не совпадают';
            statusEl.className = 'status-bar error';
            return;
        }

        const data = {
            email: formData.get('email'),
            full_name: formData.get('fullName'),
            password: password,
        };

        statusEl.textContent = 'Регистрация...';
        statusEl.className = 'status-bar';

        try {
            const response = await fetch(`${API_BASE_URL}/auth/register/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(data),
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Ошибка регистрации');
            }

            const result = await response.json();
            saveTokens(result.access_token, result.refresh_token, {
                id: result.id,
                email: result.email,
                full_name: result.full_name,
                picture_url: result.picture_url,
                auth_provider: result.auth_provider,
            });

            // Загружаем настройки пользователя
            await loadUserSettings();

            statusEl.textContent = 'Регистрация успешна! Перенаправление...';
            statusEl.className = 'status-bar success';
            setTimeout(() => {
                window.location.href = 'index.html';
            }, 1000);
        } catch (error) {
            statusEl.textContent = `Ошибка: ${error.message}`;
            statusEl.className = 'status-bar error';
        }
    });
}

// Google OAuth
function initGoogleAuth() {
    const googleBtn = document.getElementById('googleLoginBtn') || document.getElementById('googleRegisterBtn');
    if (!googleBtn) return;

    googleBtn.addEventListener('click', async () => {
        try {
            const response = await fetch(`${API_BASE_URL}/auth/google/login`);
            if (!response.ok) {
                throw new Error('Failed to get Google login URL');
            }
            const data = await response.json();
            window.location.href = data.login_url;
        } catch (error) {
            const statusEl = document.getElementById('authStatus');
            if (statusEl) {
                statusEl.textContent = `Ошибка: ${error.message}`;
                statusEl.className = 'status-bar error';
            }
        }
    });
}

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', () => {
    initGoogleAuth();

    // Если пользователь уже авторизован и находится на страницах входа/регистрации,
    // перенаправляем на главную
    if (isAuthenticated() && (window.location.pathname.includes('login.html') || window.location.pathname.includes('register.html'))) {
        window.location.href = 'index.html';
    }

    // Обновляем UI пользователя
    updateUserUI();

    // Загружаем и применяем настройки на главной странице
    if (window.location.pathname.includes('index.html')) {
        loadUserSettings().then(() => {
            applyUserSettings();
            setupSettingsAutoSave();
            // Синхронизируем настройки из Redis
            syncSettingsFromRedis();
        });
    }
});

// Экспорт функций для использования в других файлах
window.auth = {
    getAccessToken,
    getRefreshToken,
    getUserInfo,
    isAuthenticated,
    logout,
    authFetch,
    loadUserSettings,
    getUserSettings,
    updateUserUI
};