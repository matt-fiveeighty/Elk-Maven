from __future__ import annotations

"""Image upload and markup API routes."""

import json
import logging
import os
import uuid
from pathlib import Path

from flask import Blueprint, request, jsonify, current_app, send_file

from ..app import get_repo

logger = logging.getLogger(__name__)

images_bp = Blueprint("images", __name__)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}
ALLOWED_MIMETYPES = {
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp",
}


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@images_bp.route("/images/upload", methods=["POST"])
def upload_image():
    """Upload an image file.

    Accepts multipart form data with 'file' and optional 'session_id'.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename or not _allowed_file(file.filename):
        return jsonify({"error": "Invalid file type"}), 400

    session_id = request.form.get("session_id", type=int)

    # Generate unique filename
    ext = file.filename.rsplit(".", 1)[1].lower()
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    upload_dir = current_app.config["UPLOAD_FOLDER"]
    file_path = os.path.join(upload_dir, unique_name)

    # Save file
    file.save(file_path)
    file_size = os.path.getsize(file_path)

    # Get image dimensions
    width, height = None, None
    try:
        from PIL import Image
        with Image.open(file_path) as img:
            width, height = img.size
    except ImportError:
        logger.warning("Pillow not installed — cannot read image dimensions")
    except Exception as e:
        logger.warning(f"Could not read image dimensions: {e}")

    # Store in database
    repo = get_repo(current_app)
    image_id = repo.insert_uploaded_image({
        "session_id": session_id,
        "filename": file.filename,
        "mime_type": file.content_type or f"image/{ext}",
        "file_path": unique_name,  # Relative to uploads dir
        "file_size": file_size,
        "width": width,
        "height": height,
    })

    return jsonify({
        "image_id": image_id,
        "filename": file.filename,
        "url": f"/api/images/{image_id}",
        "width": width,
        "height": height,
    }), 201


@images_bp.route("/images/<int:image_id>", methods=["GET"])
def get_image(image_id):
    """Serve an uploaded image."""
    repo = get_repo(current_app)
    image = repo.get_image(image_id)
    if not image:
        return jsonify({"error": "Image not found"}), 404

    file_path = os.path.join(current_app.config["UPLOAD_FOLDER"], image["file_path"])
    if not os.path.exists(file_path):
        return jsonify({"error": "Image file missing"}), 404

    return send_file(file_path, mimetype=image["mime_type"])


@images_bp.route("/images/<int:image_id>/markup", methods=["GET"])
def get_markup(image_id):
    """Get markup data for an image."""
    repo = get_repo(current_app)
    image = repo.get_image(image_id)
    if not image:
        return jsonify({"error": "Image not found"}), 404

    markup = {}
    if image.get("markup_data"):
        try:
            markup = json.loads(image["markup_data"])
        except (json.JSONDecodeError, TypeError):
            pass

    return jsonify({"image_id": image_id, "markup_data": markup})


@images_bp.route("/images/<int:image_id>/markup", methods=["PUT"])
def save_markup(image_id):
    """Save canvas markup data for an image."""
    repo = get_repo(current_app)
    image = repo.get_image(image_id)
    if not image:
        return jsonify({"error": "Image not found"}), 404

    data = request.get_json(silent=True) or {}
    markup_data = data.get("markup_data", {})

    repo.update_image_markup(image_id, markup_data)
    return jsonify({"status": "saved"})


@images_bp.route("/images/<int:image_id>/description", methods=["PUT"])
def save_description(image_id):
    """Update description for an image."""
    repo = get_repo(current_app)
    image = repo.get_image(image_id)
    if not image:
        return jsonify({"error": "Image not found"}), 404

    data = request.get_json(silent=True) or {}
    description = data.get("description", "")

    repo.update_image_description(image_id, description)
    return jsonify({"status": "saved"})
