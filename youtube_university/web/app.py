from __future__ import annotations

"""Flask application factory for the Hunting Guru web UI."""

import logging
from pathlib import Path

from flask import Flask, render_template

from ..config import load_config, get_ollama_config
from ..database.repository import Repository
from ..agents.guru import HuntingGuru

logger = logging.getLogger(__name__)


def create_app(config: dict = None) -> Flask:
    """Create and configure the Flask application."""
    if config is None:
        config = load_config()

    app = Flask(
        __name__,
        static_folder=str(Path(__file__).parent / "static"),
        template_folder=str(Path(__file__).parent / "templates"),
    )

    # Configuration
    app.config["DB_PATH"] = config["db_path"]
    app.config["UPLOAD_FOLDER"] = str(Path(config["db_path"]).parent / "uploads")
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB max upload

    # Ensure upload directory exists
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    # Store Ollama config
    ollama_cfg = get_ollama_config(config)
    app.config["OLLAMA_URL"] = ollama_cfg["ollama_url"]
    app.config["OLLAMA_MODEL"] = ollama_cfg["model"]

    # Register blueprints
    from .routes.chat import chat_bp
    from .routes.images import images_bp
    from .routes.optimization import optimization_bp
    from .routes.status import status_bp

    app.register_blueprint(chat_bp, url_prefix="/api")
    app.register_blueprint(images_bp, url_prefix="/api")
    app.register_blueprint(optimization_bp, url_prefix="/api")
    app.register_blueprint(status_bp, url_prefix="/api")

    # Main page route
    @app.route("/")
    def index():
        return render_template("index.html")

    return app


def get_repo(app: Flask) -> Repository:
    """Get or create Repository instance for the app."""
    if not hasattr(app, "_repo") or app._repo is None:
        app._repo = Repository(app.config["DB_PATH"])
    return app._repo


def get_guru(app: Flask) -> HuntingGuru:
    """Get or create HuntingGuru instance for the app."""
    if not hasattr(app, "_guru") or app._guru is None:
        repo = get_repo(app)
        app._guru = HuntingGuru(
            repo=repo,
            ollama_url=app.config["OLLAMA_URL"],
            model=app.config["OLLAMA_MODEL"],
        )
    return app._guru
