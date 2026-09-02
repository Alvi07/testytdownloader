import base64
import logging
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

_logger = logging.getLogger("config")


def resolve_cookies_file() -> Path | None:
    """
    Resolve YouTube cookies for yt-dlp (needed on Render / cloud IPs).

    Priority:
      1. COOKIES_FILE env path (e.g. /etc/secrets/cookies.txt on Render Secret Files)
      2. YOUTUBE_COOKIES_BASE64 env (Netscape cookies.txt encoded as base64 — works on Render Free)
      3. ./cookies.txt in project root (local only; never commit this file)
    """
    cookies_env = os.environ.get("COOKIES_FILE", "").strip()
    if cookies_env:
        path = Path(cookies_env)
        if path.is_file() and path.stat().st_size > 0:
            return path

    b64 = os.environ.get("YOUTUBE_COOKIES_BASE64", "").strip()
    # Render UI sometimes wraps long env values with whitespace/newlines
    if b64:
        b64 = "".join(b64.split())
        out = DOWNLOADS_DIR.parent / ".runtime_cookies.txt"
        try:
            raw = base64.b64decode(b64, validate=False)
            if not raw or b"# Netscape" not in raw[:200] and b".youtube.com" not in raw:
                _logger.error(
                    "YOUTUBE_COOKIES_BASE64 decoded but does not look like cookies.txt"
                )
            out.write_bytes(raw)
            try:
                out.chmod(0o600)
            except Exception:
                pass
            _logger.info("Wrote runtime cookies file (%s bytes)", len(raw))
            return out
        except Exception as exc:
            _logger.error("Failed to decode YOUTUBE_COOKIES_BASE64: %s", exc)

    local = BASE_DIR / "cookies.txt"
    if local.is_file() and local.stat().st_size > 0:
        return local

    return None


COOKIES_FILE = resolve_cookies_file()


def resolve_proxy_url() -> str | None:
    """
    Optional HTTP(S)/SOCKS proxy for yt-dlp (needed on cloud IPs like Render).

    Env (first match wins):
      YOUTUBE_PROXY, PROXY_URL, HTTPS_PROXY, HTTP_PROXY

    Examples:
      http://user:pass@host:8000
      socks5://user:pass@host:1080

    Free public proxies almost never work for YouTube long-term.
    Use a residential / mobile proxy provider for reliable downloads.
    """
    for key in ("YOUTUBE_PROXY", "PROXY_URL", "HTTPS_PROXY", "HTTP_PROXY"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


PROXY_URL = resolve_proxy_url()


def proxy_is_configured() -> bool:
    return bool(PROXY_URL)