// Session management
'use strict';

async function loadSessions() {
    try {
        const resp = await fetch('/api/sessions');
        const data = await resp.json();
        renderSessionList(data.sessions);
    } catch (e) {
        console.error('Failed to load sessions:', e);
    }
}

function renderSessionList(sessions) {
    const list = document.getElementById('sessionList');
    list.innerHTML = '';

    if (!sessions.length) {
        list.innerHTML = '<div style="padding:16px;color:var(--text-dim);font-size:13px;text-align:center;">No chats yet.<br>Click + to start.</div>';
        return;
    }

    sessions.forEach(session => {
        const div = document.createElement('div');
        div.className = 'session-item' + (session.id === currentSessionId ? ' active' : '');
        div.onclick = () => loadSession(session.id);

        const preview = session.last_message
            ? session.last_message.substring(0, 60) + (session.last_message.length > 60 ? '...' : '')
            : 'Empty chat';

        div.innerHTML = `
            <div class="session-actions">
                <button onclick="event.stopPropagation(); deleteSession(${session.id})" title="Delete">🗑️</button>
            </div>
            <div class="session-title">${escapeHtml(session.title || 'New Chat')}</div>
            <div class="session-preview">${escapeHtml(preview)}</div>
        `;
        list.appendChild(div);
    });
}

async function createNewSession() {
    try {
        const resp = await fetch('/api/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: 'New Chat' }),
        });
        const data = await resp.json();
        currentSessionId = data.session_id;

        // Clear chat area
        const messages = document.getElementById('messages');
        messages.innerHTML = '';

        // Show welcome
        const welcome = document.getElementById('welcomeMessage');
        if (!welcome) {
            messages.innerHTML = `
                <div class="welcome-message" id="welcomeMessage">
                    <h2>New Chat</h2>
                    <p>Ask the Hunting Guru anything.</p>
                </div>
            `;
        }

        // Clear attachments
        pendingImageIds = [];
        document.getElementById('inputAttachments').innerHTML = '';

        loadSessions();
        document.getElementById('messageInput').focus();
    } catch (e) {
        console.error('Failed to create session:', e);
    }
}

async function loadSession(sessionId) {
    currentSessionId = sessionId;

    const messages = document.getElementById('messages');
    messages.innerHTML = '';

    // Clear attachments
    pendingImageIds = [];
    document.getElementById('inputAttachments').innerHTML = '';

    try {
        const resp = await fetch(`/api/sessions/${sessionId}`);
        const data = await resp.json();

        if (!data.messages.length) {
            messages.innerHTML = `
                <div class="welcome-message" id="welcomeMessage">
                    <h2>Empty Chat</h2>
                    <p>Start typing to ask the Guru.</p>
                </div>
            `;
        } else {
            data.messages.forEach(msg => {
                let imageUrls = [];
                if (msg.image_ids && msg.image_ids.length) {
                    imageUrls = msg.image_ids.map(id => `/api/images/${id}`);
                }
                const route = msg.metadata?.route || null;
                addMessageToUI(msg.role, msg.content, imageUrls, route);
            });
        }

        // Highlight active session
        document.querySelectorAll('.session-item').forEach(el => el.classList.remove('active'));
        loadSessions();
    } catch (e) {
        console.error('Failed to load session:', e);
    }
}

async function deleteSession(sessionId) {
    if (!confirm('Delete this chat?')) return;

    try {
        await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });

        if (currentSessionId === sessionId) {
            currentSessionId = null;
            document.getElementById('messages').innerHTML = `
                <div class="welcome-message" id="welcomeMessage">
                    <h2>Welcome to Hunting Guru</h2>
                    <p>Click + to start a new chat.</p>
                </div>
            `;
        }

        loadSessions();
    } catch (e) {
        console.error('Failed to delete session:', e);
    }
}
