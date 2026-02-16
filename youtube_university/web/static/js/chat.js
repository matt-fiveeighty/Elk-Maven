// Chat-specific utilities (placeholder for future enhancements)
// Core chat logic is in app.js — this file handles message rendering extras
'use strict';

// Format message body with basic markdown-like styling
function formatMessage(text) {
    // This is intentionally simple — no heavy markdown parser
    let html = escapeHtml(text);

    // Bold: **text**
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

    // Numbered lists: lines starting with digits
    html = html.replace(/^(\d+\.\s)/gm, '<strong>$1</strong>');

    return html;
}
