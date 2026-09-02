import os
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
DOWNLOADS_DIR = BASE_DIR / "temp_downloads"
STATIC_DIR = BASE_DIR / "static"

# Ensure temp directory exists
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Application configurations
APP_TITLE = "ProStream - Advanced Media Downloader"
APP_DESCRIPTION = "High-performance YouTube, Shorts, Reels & Video Downloader"
MAX_FILE_AGE_SECONDS = 600  # Automatically delete downloaded files older than 10 minutes
PORT = int(os.environ.get("PORT", 8000))
HOST = os.environ.get("HOST", "0.0.0.0")

# User Agent for yt-dlp to prevent 403 Forbidden errors
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
