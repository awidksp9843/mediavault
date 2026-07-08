"""
MediaVault - Configuration & Logging Setup
Loads .env, manages paths with pathlib, configures centralized logging.
"""
import logging
import sys
from pathlib import Path
from dotenv import load_dotenv
import os

# ── Load .env from project root ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ── Server ──
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))
FRONTEND_PORT = int(os.getenv("FRONTEND_PORT", "5173"))
BIND_HOST = os.getenv("BIND_HOST", "127.0.0.1")

# ── Database ──
DB_PATH = Path(os.getenv("DB_PATH", "./data/mediavault.db"))
if not DB_PATH.is_absolute():
    DB_PATH = PROJECT_ROOT / DB_PATH
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# ── Thumbnails ──
THUMBNAIL_DIR = Path(os.getenv("THUMBNAIL_DIR", "./data/thumbnails"))
if not THUMBNAIL_DIR.is_absolute():
    THUMBNAIL_DIR = PROJECT_ROOT / THUMBNAIL_DIR
THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
THUMBNAIL_MAX_SIZE = int(os.getenv("THUMBNAIL_MAX_SIZE", "400"))
THUMBNAIL_FORMAT = os.getenv("THUMBNAIL_FORMAT", "webp")

# ── Logging ──
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_DIR = Path(os.getenv("LOG_DIR", "./logs"))
if not LOG_DIR.is_absolute():
    LOG_DIR = PROJECT_ROOT / LOG_DIR
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ── Supported Extensions ──
SUPPORTED_IMAGE_EXTENSIONS = set(
    os.getenv(
        "SUPPORTED_IMAGE_EXTENSIONS",
        ".jpg,.jpeg,.png,.gif,.bmp,.tiff,.tif,.webp,.heic,.heif,.avif,.raw,.cr2,.nef,.arw"
    ).split(",")
)
SUPPORTED_VIDEO_EXTENSIONS = set(
    os.getenv(
        "SUPPORTED_VIDEO_EXTENSIONS",
        ".mp4,.mkv,.avi,.mov,.wmv,.flv,.webm,.m4v,.3gp,.mpg,.mpeg"
    ).split(",")
)
ALL_SUPPORTED_EXTENSIONS = SUPPORTED_IMAGE_EXTENSIONS | SUPPORTED_VIDEO_EXTENSIONS


def get_media_type(extension: str) -> str | None:
    """Return 'image' or 'video' based on file extension, or None if unsupported."""
    ext = extension.lower()
    if ext in SUPPORTED_IMAGE_EXTENSIONS:
        return "image"
    if ext in SUPPORTED_VIDEO_EXTENSIONS:
        return "video"
    return None


# ── Centralized Logging ──
def setup_logging() -> logging.Logger:
    """Configure centralized logging with file + console handlers."""
    logger = logging.getLogger("mediavault")
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(name)s.%(funcName)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler
    file_handler = logging.FileHandler(LOG_DIR / "mediavault.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


logger = setup_logging()
