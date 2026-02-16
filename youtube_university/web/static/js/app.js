// Hunting Guru — Main App Controller
'use strict';

let currentSessionId = null;
let pendingImageIds = [];

document.addEventListener('DOMContentLoaded', () => {
    loadSessions();
    loadStatus();

    document.getElementById('newChatBtn').addEventListener('click', createNewSession);
    document.getElementById('sendBtn').addEventListener('click', sendMessage);
    document.getElementById('fileInput').addEventListener('change', handleFileUpload);

    const input = document.getElementById('messageInput');
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    input.addEventListener('input', autoResize);
});

function autoResize() {
    const el = document.getElementById('messageInput');
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

async function loadStatus() {
    try {
        const resp = await fetch('/api/status');
        const data = await resp.json();
        const stats = data.ingestion;
        const analyzed = stats.videos_by_status?.analyzed || 0;
        document.getElementById('headerStats').textContent =
            `${stats.knowledge_entries} entries | ${analyzed} videos analyzed | ${stats.channels} channels`;
    } catch (e) {
        console.error('Failed to load status:', e);
    }
}

function quickAsk(text) {
    // Start a new session and ask the question
    createNewSession().then(() => {
        document.getElementById('messageInput').value = text;
        sendMessage();
    });
}

async function sendMessage() {
    const input = document.getElementById('messageInput');
    const message = input.value.trim();
    if (!message) return;

    // Ensure we have a session
    if (!currentSessionId) {
        await createNewSession();
    }

    // Clear input
    input.value = '';
    input.style.height = 'auto';

    // Hide welcome message
    const welcome = document.getElementById('welcomeMessage');
    if (welcome) welcome.style.display = 'none';

    // Add user message to UI
    addMessageToUI('user', message, pendingImageIds.map(id => `/api/images/${id}`));

    // Collect image IDs and clear attachments
    const imageIds = [...pendingImageIds];
    pendingImageIds = [];
    document.getElementById('inputAttachments').innerHTML = '';

    // Show thinking indicator
    showThinking();

    // Disable send button
    document.getElementById('sendBtn').disabled = true;

    try {
        const resp = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: currentSessionId,
                message: message,
                image_ids: imageIds,
            }),
        });
        const data = await resp.json();

        hideThinking();
        addMessageToUI('assistant', data.response, [], data.route);

        // Refresh session list (title may have changed)
        loadSessions();
    } catch (e) {
        hideThinking();
        addMessageToUI('assistant', 'Sorry, something went wrong. Is Ollama running?');
    } finally {
        document.getElementById('sendBtn').disabled = false;
        document.getElementById('messageInput').focus();
    }
}

function addMessageToUI(role, content, imageUrls = [], route = null) {
    const container = document.getElementById('messages');
    const div = document.createElement('div');
    div.className = `message ${role}`;

    let headerText = role === 'user' ? 'You' : 'Guru';
    let routeBadge = '';
    if (route && route !== 'general' && route !== 'error') {
        routeBadge = `<span class="route-badge">${route}</span>`;
    }

    let imagesHtml = '';
    if (imageUrls && imageUrls.length) {
        imagesHtml = '<div class="message-images">' +
            imageUrls.map(url => {
                const imgId = url.split('/').pop();
                return `<img src="${url}" onclick="openMarkup(${imgId})" alt="Uploaded image">`;
            }).join('') + '</div>';
    }

    div.innerHTML = `
        <div class="message-header">${headerText}${routeBadge}</div>
        <div class="message-body">${escapeHtml(content)}</div>
        ${imagesHtml}
    `;

    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function showThinking() {
    const container = document.getElementById('messages');
    const div = document.createElement('div');
    div.id = 'thinkingIndicator';
    div.className = 'thinking';
    div.innerHTML = `
        Thinking
        <div class="thinking-dots">
            <span></span><span></span><span></span>
        </div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function hideThinking() {
    const el = document.getElementById('thinkingIndicator');
    if (el) el.remove();
}

async function handleFileUpload(e) {
    const file = e.target.files[0];
    if (!file) return;

    // Ensure we have a session
    if (!currentSessionId) {
        await createNewSession();
    }

    const formData = new FormData();
    formData.append('file', file);
    formData.append('session_id', currentSessionId);

    try {
        const resp = await fetch('/api/images/upload', {
            method: 'POST',
            body: formData,
        });
        const data = await resp.json();

        pendingImageIds.push(data.image_id);

        // Show preview
        const container = document.getElementById('inputAttachments');
        const preview = document.createElement('div');
        preview.className = 'attachment-preview';
        preview.dataset.imageId = data.image_id;
        preview.innerHTML = `
            <img src="${data.url}" alt="Attachment">
            <button class="attachment-remove" onclick="removeAttachment(${data.image_id}, this)">✕</button>
        `;
        container.appendChild(preview);
    } catch (err) {
        console.error('Upload failed:', err);
    }

    // Reset file input
    e.target.value = '';
}

function removeAttachment(imageId, btn) {
    pendingImageIds = pendingImageIds.filter(id => id !== imageId);
    btn.parentElement.remove();
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
