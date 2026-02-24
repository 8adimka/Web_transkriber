// edit_profile.js - Логика страницы редактирования профиля

document.addEventListener('DOMContentLoaded', function () {
    // Проверка авторизации
    checkAuth();

    // Загрузка профиля
    loadProfile();

    // Настройка обработчиков событий
    document.getElementById('saveProfileBtn').addEventListener('click', saveProfile);
    document.getElementById('cancelBtn').addEventListener('click', cancelEdit);
    document.getElementById('changePasswordBtn').addEventListener('click', changePassword);
    document.getElementById('uploadAvatarBtn').addEventListener('click', uploadAvatar);
    document.getElementById('removeAvatarBtn').addEventListener('click', removeAvatar);
    document.getElementById('avatarUrl').addEventListener('input', updateAvatarPreview);
    document.getElementById('newPassword').addEventListener('input', checkPasswordStrength);
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
        // Загружаем профиль
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

        // Обновляем форму
        updateProfileForm(data);

        // Скрываем загрузку, показываем контент
        document.getElementById('loading').style.display = 'none';
        document.getElementById('profileContent').style.display = 'block';

    } catch (error) {
        console.error('Ошибка загрузки профиля:', error);
        showError(`Не удалось загрузить профиль: ${error.message}`);
    }
}

// Обновление формы профиля
function updateProfileForm(data) {
    const { profile } = data;
    const user = profile.user;
    const settings = profile.settings;

    // Аватар
    const avatarUrl = user.picture_url || settings.avatar_url;
    if (avatarUrl) {
        document.getElementById('currentAvatar').src = avatarUrl;
        document.getElementById('avatarUrl').value = avatarUrl;
    }

    // Личная информация
    document.getElementById('fullName').value = user.full_name || '';
    document.getElementById('email').value = user.email;

    // Дата регистрации
    const regDate = new Date(user.created_at);
    document.getElementById('createdAt').value = regDate.toLocaleDateString('ru-RU');
}

// Проверка сложности пароля
function checkPasswordStrength() {
    const password = document.getElementById('newPassword').value;
    const strengthDiv = document.getElementById('passwordStrength');

    if (!password) {
        strengthDiv.textContent = '';
        return;
    }

    let strength = 0;
    let message = '';
    let className = '';

    // Проверка длины
    if (password.length >= 8) strength++;
    if (password.length >= 12) strength++;

    // Проверка наличия разных типов символов
    if (/[a-z]/.test(password)) strength++;
    if (/[A-Z]/.test(password)) strength++;
    if (/[0-9]/.test(password)) strength++;
    if (/[^a-zA-Z0-9]/.test(password)) strength++;

    if (strength <= 2) {
        message = 'Слабый пароль';
        className = 'strength-weak';
    } else if (strength <= 4) {
        message = 'Средний пароль';
        className = 'strength-medium';
    } else {
        message = 'Сильный пароль';
        className = 'strength-strong';
    }

    strengthDiv.textContent = message;
    strengthDiv.className = `password-strength ${className}`;
}

// Обновление предпросмотра аватара
function updateAvatarPreview() {
    const url = document.getElementById('avatarUrl').value;
    if (url) {
        document.getElementById('currentAvatar').src = url;
    }
}

// Сохранение профиля
async function saveProfile() {
    const token = localStorage.getItem('access_token');
    if (!token) return;

    const fullName = document.getElementById('fullName').value.trim();
    const avatarUrl = document.getElementById('avatarUrl').value.trim();

    try {
        // Обновление имени пользователя (если есть API)
        if (fullName) {
            const response = await fetch('/user/profile', {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    full_name: fullName,
                    picture_url: avatarUrl || null
                })
            });

            if (!response.ok) {
                throw new Error(`Ошибка обновления профиля: ${response.status}`);
            }

            // Обновляем локальные данные
            const userInfo = JSON.parse(localStorage.getItem('user_info') || '{}');
            userInfo.full_name = fullName;
            userInfo.picture_url = avatarUrl || null;
            localStorage.setItem('user_info', JSON.stringify(userInfo));

            showSuccess('Профиль успешно обновлен!');
        }

        // Обновление URL аватара в настройках
        if (avatarUrl) {
            const settingsResponse = await fetch('/user/settings', {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    avatar_url: avatarUrl
                })
            });

            if (!settingsResponse.ok) {
                throw new Error(`Ошибка обновления аватара: ${settingsResponse.status}`);
            }
        }

        showSuccess('Профиль успешно обновлен! Перенаправление на страницу профиля...');

        // Редирект на страницу профиля через 2 секунды
        setTimeout(() => {
            window.location.href = 'profile.html';
        }, 2000);

    } catch (error) {
        console.error('Ошибка сохранения профиля:', error);
        showError(`Не удалось сохранить профиль: ${error.message}`);
    }
}

// Смена пароля
async function changePassword() {
    const token = localStorage.getItem('access_token');
    if (!token) return;

    const currentPassword = document.getElementById('currentPassword').value;
    const newPassword = document.getElementById('newPassword').value;
    const confirmPassword = document.getElementById('confirmPassword').value;

    // Валидация
    if (!currentPassword) {
        showError('Введите текущий пароль');
        return;
    }

    if (!newPassword) {
        showError('Введите новый пароль');
        return;
    }

    if (newPassword !== confirmPassword) {
        showError('Новые пароли не совпадают');
        return;
    }

    if (newPassword.length < 8) {
        showError('Новый пароль должен быть не менее 8 символов');
        return;
    }

    try {
        const response = await fetch('/user/change-password', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                current_password: currentPassword,
                new_password: newPassword
            })
        });

        if (!response.ok) {
            if (response.status === 401) {
                throw new Error('Текущий пароль неверен');
            }
            throw new Error(`Ошибка смены пароля: ${response.status}`);
        }

        // Очищаем поля паролей
        document.getElementById('currentPassword').value = '';
        document.getElementById('newPassword').value = '';
        document.getElementById('confirmPassword').value = '';
        document.getElementById('passwordStrength').textContent = '';

        showSuccess('Пароль успешно изменен!');

    } catch (error) {
        console.error('Ошибка смены пароля:', error);
        showError(`Не удалось сменить пароль: ${error.message}`);
    }
}

// Загрузка аватара
function uploadAvatar() {
    alert('Функция загрузки файлов будет реализована в будущем. Пока используйте URL.');
}

// Удаление аватара
function removeAvatar() {
    if (confirm('Удалить текущий аватар?')) {
        document.getElementById('avatarUrl').value = '';
        document.getElementById('currentAvatar').src = 'https://via.placeholder.com/100';
    }
}

// Отмена редактирования
function cancelEdit() {
    if (confirm('Отменить изменения и вернуться в профиль?')) {
        window.location.href = 'profile.html';
    }
}

// Показ ошибки
function showError(message) {
    const errorDiv = document.getElementById('error');
    errorDiv.textContent = message;
    errorDiv.style.display = 'block';

    // Скрываем успешное сообщение если было
    document.getElementById('success').style.display = 'none';

    // Автоматически скрываем через 5 секунд
    setTimeout(() => {
        errorDiv.style.display = 'none';
    }, 5000);
}

// Показ успешного сообщения
function showSuccess(message) {
    const successDiv = document.getElementById('success');
    successDiv.textContent = message;
    successDiv.style.display = 'block';

    // Скрываем ошибку если была
    document.getElementById('error').style.display = 'none';

    // Автоматически скрываем через 3 секунд
    setTimeout(() => {
        successDiv.style.display = 'none';
    }, 3000);
}