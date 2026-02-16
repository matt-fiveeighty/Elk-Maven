from __future__ import annotations

"""Chat API routes — sessions, messages, and guru interaction."""

import json
import logging

from flask import Blueprint, request, jsonify, current_app

from ..app import get_repo, get_guru

logger = logging.getLogger(__name__)

chat_bp = Blueprint("chat", __name__)


@chat_bp.route("/sessions", methods=["GET"])
def list_sessions():
    """List all chat sessions."""
    repo = get_repo(current_app)
    sessions = repo.get_all_sessions()
    return jsonify({"sessions": sessions})


@chat_bp.route("/sessions", methods=["POST"])
def create_session():
    """Create a new chat session."""
    repo = get_repo(current_app)
    data = request.get_json(silent=True) or {}
    title = data.get("title", "New Chat")
    session_id = repo.create_chat_session(title)
    return jsonify({"session_id": session_id, "title": title}), 201


@chat_bp.route("/sessions/<int:session_id>", methods=["GET"])
def get_session(session_id):
    """Get all messages for a session."""
    repo = get_repo(current_app)
    messages = repo.get_session_messages(session_id)
    # Parse image_ids and metadata from JSON strings
    for msg in messages:
        if msg.get("image_ids"):
            try:
                msg["image_ids"] = json.loads(msg["image_ids"])
            except (json.JSONDecodeError, TypeError):
                msg["image_ids"] = []
        if msg.get("metadata"):
            try:
                msg["metadata"] = json.loads(msg["metadata"])
            except (json.JSONDecodeError, TypeError):
                msg["metadata"] = {}
    return jsonify({"messages": messages})


@chat_bp.route("/sessions/<int:session_id>", methods=["DELETE"])
def delete_session(session_id):
    """Delete a chat session."""
    repo = get_repo(current_app)
    repo.delete_session(session_id)
    return jsonify({"status": "deleted"})


@chat_bp.route("/sessions/<int:session_id>", methods=["PATCH"])
def rename_session(session_id):
    """Rename a chat session."""
    repo = get_repo(current_app)
    data = request.get_json(silent=True) or {}
    title = data.get("title", "")
    if title:
        repo.rename_session(session_id, title)
    return jsonify({"status": "updated"})


@chat_bp.route("/chat", methods=["POST"])
def send_message():
    """Send a message and get a guru response.

    Body: {"session_id": int, "message": str, "image_ids": [int]}
    """
    repo = get_repo(current_app)
    guru = get_guru(current_app)
    data = request.get_json(silent=True) or {}

    session_id = data.get("session_id")
    message = data.get("message", "").strip()
    image_ids = data.get("image_ids", [])

    if not session_id or not message:
        return jsonify({"error": "session_id and message required"}), 400

    # Load conversation history into guru
    history = repo.get_session_messages(session_id, limit=20)
    guru.history = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in history
        if msg["role"] in ("user", "assistant")
    ]

    # If images attached, add their descriptions to the message
    enriched_message = message
    if image_ids:
        image_descs = []
        for img_id in image_ids:
            img = repo.get_image(img_id)
            if img:
                desc = img.get("description") or img.get("filename", "uploaded image")
                image_descs.append(f"[Attached image: {desc}]")
        if image_descs:
            enriched_message = " ".join(image_descs) + "\n\n" + message

    # Save user message
    user_msg_id = repo.insert_chat_message(
        session_id, "user", message,
        image_ids=image_ids if image_ids else None,
    )

    # Get guru response
    try:
        response = guru.chat(enriched_message)
        route = guru._detect_route(message)
    except Exception as e:
        logger.exception("Guru chat error")
        response = f"Sorry, I encountered an error: {str(e)}"
        route = "error"

    # Save assistant response
    assistant_msg_id = repo.insert_chat_message(
        session_id, "assistant", response,
        metadata={"route": route},
    )

    # Auto-title the session after first exchange
    sessions = repo.get_all_sessions()
    for s in sessions:
        if s["id"] == session_id and s["title"] == "New Chat" and s["message_count"] <= 2:
            # Use first ~50 chars of the first message as the title
            auto_title = message[:50] + ("..." if len(message) > 50 else "")
            repo.rename_session(session_id, auto_title)
            break

    return jsonify({
        "response": response,
        "user_message_id": user_msg_id,
        "assistant_message_id": assistant_msg_id,
        "route": route,
    })
