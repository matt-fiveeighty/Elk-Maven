from __future__ import annotations

"""Status API route."""

from flask import Blueprint, jsonify, current_app

from ..app import get_repo

status_bp = Blueprint("status", __name__)


@status_bp.route("/status", methods=["GET"])
def get_status():
    """Get full system status as JSON."""
    repo = get_repo(current_app)
    stats = repo.get_ingestion_stats()
    bias = repo.get_bias_summary()
    pending_queue = repo.get_pending_queue_items()

    return jsonify({
        "ingestion": stats,
        "bias": bias,
        "optimization_queue_pending": len(pending_queue),
    })
