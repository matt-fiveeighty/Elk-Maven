import logging
import sys
from pathlib import Path


def setup_logging(log_file: str = None, level: str = "INFO") -> logging.Logger:
    """Configure logging to both console and optional file."""
    root_logger = logging.getLogger("youtube_university")
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Avoid duplicate handlers on repeated calls
    if root_logger.handlers:
        return root_logger

    # Console handler
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root_logger.addHandler(console)

    # File handler
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        root_logger.addHandler(file_handler)

    return root_logger
