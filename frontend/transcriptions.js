// Элементы DOM
const transcriptionsList = document.getElementById('transcriptionsList');
const transcriptionsInfo = document.getElementById('transcriptionsInfo');
const pagination = document.getElementById('pagination');
const deleteModal = document.getElementById('deleteModal');
const cancelDeleteBtn = document.getElementById('cancelDelete');
const confirmDeleteBtn = document.getElementById('confirmDelete');
const logoutBtn = document.getElementById('logoutBtn');

// Состояние
let currentPage = 1;
const itemsPerPage = 10;
let totalItems = 0;
let transcriptions = [];
let transcriptionToDelete = null;

// Инициализация
function init() {
    checkAuth();
    loadTranscriptions();
    setupEventListeners();
}

// Проверка аутентификации
function checkAuth() {
    const token = localStorage.getItem('access_token');
    if (!token) {
        alert('Для просмотра транскрипций необходимо войти в систему.');
        window.location.href = 'login.html';
        return false;
    }
    return true;
}

// Настройка обработчиков событий
function setupEventListeners() {
    if (logoutBtn) {
        logoutBtn.addEventListener('click', () => {
            localStorage.removeItem('access_token');
            localStorage.removeItem('refresh_token');
            localStorage.removeItem('user_info');
            window.location.href = 'login.html';
        });
    }

    if (cancelDeleteBtn) {
        cancelDeleteBtn.addEventListener('click', () => {
            deleteModal.style.display = 'none';
            transcriptionToDelete = null;
        });
    }

    if (confirmDeleteBtn) {
        confirmDeleteBtn.addEventListener('click', deleteTranscription);
    }
}

// Загрузка транскрипций
async function loadTranscriptions(page = 1) {
    const token = localStorage.getItem('access_token');
    if (!token) {
        window.location.href = 'login.html';
        return;
    }

    try {
        const skip = (page - 1) * itemsPerPage;
        // Пробуем оба варианта - со слешем и без
        let url = `/transcriptions?skip=${skip}&limit=${itemsPerPage}&token=${encodeURIComponent(token)}`;
        let response = await fetch(url, { redirect: 'follow' });

        // Если получили редирект, пробуем без слеша
        if (response.redirected) {
            url = `/transcriptions?skip=${skip}&limit=${itemsPerPage}&token=${encodeURIComponent(token)}`;
            response = await fetch(url, { redirect: 'follow' });
        }

        if (response.status === 401) {
            alert('Сессия истекла. Пожалуйста, войдите снова.');
            window.location.href = 'login.html';
            return;
        }

        if (!response.ok) {
            throw new Error(`Ошибка загрузки: ${response.status}`);
        }

        const data = await response.json();
        transcriptions = data.transcriptions;
        totalItems = data.total;
        currentPage = page;

        renderTranscriptions();
        renderPagination();
        updateInfo();
    } catch (error) {
        console.error('Ошибка загрузки транскрипций:', error);
        transcriptionsList.innerHTML = `<div class="error">Ошибка загрузки транскрипций: ${error.message}</div>`;
    }
}

// Отображение транскрипций
function renderTranscriptions() {
    if (transcriptions.length === 0) {
        transcriptionsList.innerHTML = `
            <div class="empty-state">
                <p>У вас пока нет сохранённых транскрипций.</p>
                <p>Вернитесь на <a href="index.html">главную страницу</a>, чтобы создать первую транскрипцию.</p>
            </div>
        `;
        return;
    }

    const html = transcriptions.map(transcription => `
        <div class="transcription-item" data-id="${transcription.id}">
            <div class="transcription-header">
                <div class="transcription-title">
                    <h3>${formatDate(transcription.created_at)}</h3>
                    <span class="transcription-meta">
                        ${transcription.orig_language}${transcription.translate_to ? ` → ${transcription.translate_to}` : ''}
                        ${transcription.file_size ? ` • ${formatFileSize(transcription.file_size)}` : ''}
                    </span>
                </div>
                <div class="transcription-actions">
                    <button class="button small" onclick="downloadTranscription(${transcription.id})">
                        📥 Скачать
                    </button>
                    <button class="button small danger" onclick="showDeleteModal(${transcription.id})">
                        🗑️ Удалить
                    </button>
                </div>
            </div>
            <div class="transcription-preview">
                ${truncateText(transcription.content, 200)}
            </div>
        </div>
    `).join('');

    transcriptionsList.innerHTML = html;
}

// Отображение пагинации
function renderPagination() {
    if (totalItems <= itemsPerPage) {
        pagination.innerHTML = '';
        return;
    }

    const totalPages = Math.ceil(totalItems / itemsPerPage);
    let html = '<div class="pagination-controls">';

    if (currentPage > 1) {
        html += `<button class="button small" onclick="loadTranscriptions(${currentPage - 1})">← Назад</button>`;
    }

    html += `<span class="page-info">Страница ${currentPage} из ${totalPages}</span>`;

    if (currentPage < totalPages) {
        html += `<button class="button small" onclick="loadTranscriptions(${currentPage + 1})">Вперёд →</button>`;
    }

    html += '</div>';
    pagination.innerHTML = html;
}

// Обновление информации
function updateInfo() {
    const start = (currentPage - 1) * itemsPerPage + 1;
    const end = Math.min(currentPage * itemsPerPage, totalItems);

    if (totalItems === 0) {
        transcriptionsInfo.textContent = 'Нет транскрипций';
    } else {
        transcriptionsInfo.textContent = `Показано ${start}-${end} из ${totalItems} транскрипций`;
    }
}

// Скачивание транскрипции
async function downloadTranscription(id) {
    const token = localStorage.getItem('access_token');
    if (!token) {
        window.location.href = 'login.html';
        return;
    }

    try {
        const response = await fetch(`/transcriptions/${id}/download?token=${encodeURIComponent(token)}`);

        if (response.status === 401) {
            alert('Сессия истекла. Пожалуйста, войдите снова.');
            window.location.href = 'login.html';
            return;
        }

        if (!response.ok) {
            throw new Error(`Ошибка скачивания: ${response.status}`);
        }

        // Получаем имя файла из заголовков
        const contentDisposition = response.headers.get('Content-Disposition');
        let filename = `transcription_${id}.txt`;
        if (contentDisposition) {
            // Пробуем разные форматы заголовка Content-Disposition
            let match = contentDisposition.match(/filename="(.+?)"/);  // С кавычками
            if (!match) {
                match = contentDisposition.match(/filename=([^;]+)/);  // Без кавычек
            }
            if (match) {
                filename = match[1].trim();
                // Убираем кавычки, если они есть
                if (filename.startsWith('"') && filename.endsWith('"')) {
                    filename = filename.slice(1, -1);
                }
            }
        }

        // Создаем blob и скачиваем
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    } catch (error) {
        console.error('Ошибка скачивания:', error);
        alert(`Ошибка скачивания: ${error.message}`);
    }
}

// Показать модальное окно удаления
function showDeleteModal(id) {
    transcriptionToDelete = id;
    deleteModal.style.display = 'flex';
}

// Удаление транскрипции
async function deleteTranscription() {
    if (!transcriptionToDelete) return;

    const token = localStorage.getItem('access_token');
    if (!token) {
        window.location.href = 'login.html';
        return;
    }

    try {
        const response = await fetch(`/transcriptions/${transcriptionToDelete}?token=${encodeURIComponent(token)}`, {
            method: 'DELETE'
        });

        if (response.status === 401) {
            alert('Сессия истекла. Пожалуйста, войдите снова.');
            window.location.href = 'login.html';
            return;
        }

        if (!response.ok) {
            throw new Error(`Ошибка удаления: ${response.status}`);
        }

        // Закрываем модальное окно и обновляем список
        deleteModal.style.display = 'none';
        transcriptionToDelete = null;

        // Перезагружаем текущую страницу
        loadTranscriptions(currentPage);

        // Не показываем дополнительное окно подтверждения
        // Просто обновляем список (уже сделано выше)
    } catch (error) {
        console.error('Ошибка удаления:', error);
        // Не показываем alert при ошибке, можно добавить уведомление в интерфейсе
        // alert(`Ошибка удаления: ${error.message}`);
    }
}

// Вспомогательные функции
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleString('ru-RU', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' Б';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' КБ';
    return (bytes / (1024 * 1024)).toFixed(1) + ' МБ';
}

function truncateText(text, maxLength) {
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
}

// Глобальные функции для использования в HTML
window.downloadTranscription = downloadTranscription;
window.showDeleteModal = showDeleteModal;
window.loadTranscriptions = loadTranscriptions;

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', init);