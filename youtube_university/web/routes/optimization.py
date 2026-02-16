from __future__ import annotations

"""Optimization queue and bias report API routes."""

import logging

from flask import Blueprint, jsonify, current_app

from ..app import get_repo

logger = logging.getLogger(__name__)

optimization_bp = Blueprint("optimization", __name__)


@optimization_bp.route("/optimize/queue", methods=["GET"])
def get_queue():
    """List pending optimization suggestions."""
    repo = get_repo(current_app)
    items = repo.get_pending_queue_items()
    return jsonify({"items": items})


@optimization_bp.route("/optimize/queue/<int:item_id>/approve", methods=["POST"])
def approve_item(item_id):
    """Approve an optimization suggestion."""
    repo = get_repo(current_app)
    repo.update_queue_status(item_id, "approved", "user_web")
    return jsonify({"status": "approved"})


@optimization_bp.route("/optimize/queue/<int:item_id>/reject", methods=["POST"])
def reject_item(item_id):
    """Reject an optimization suggestion."""
    repo = get_repo(current_app)
    repo.update_queue_status(item_id, "rejected", "user_web")
    return jsonify({"status": "rejected"})


@optimization_bp.route("/bias/summary", methods=["GET"])
def bias_summary():
    """Get bias detection summary."""
    repo = get_repo(current_app)
    summary = repo.get_bias_summary()
    return jsonify(summary)
