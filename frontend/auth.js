// Утилиты для работы с токенами
const TOKEN_KEY = 'access_token';
const REFRESH_TOKEN_KEY = 'refresh_token';
const USER_INFO_KEY = 'user_info';

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
        const response = await fetch('/auth/refresh/', {
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
            const response = await fetch('/auth/token/', {
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
            const response = await fetch('/auth/register/', {
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
            const response = await fetch('/auth/google/login');
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
});