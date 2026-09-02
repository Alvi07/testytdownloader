import time
import asyncio
import logging
from pathlib import Path
from app.config import DOWNLOADS_DIR, MAX_FILE_AGE_SECONDS

logger = logging.getLogger("downloader.cleaner")

def cleanup_stale_files():
    """Remove files in the downloads directory older than MAX_FILE_AGE_SECONDS."""
    try:
        now = time.time()
        count = 0
        for item in DOWNLOADS_DIR.iterdir():
            if item.is_file():
                age = now - item.stat().st_mtime
                if age > MAX_FILE_AGE_SECONDS:
                    try:
                        item.unlink(missing_ok=True)
                        count += 1
                    except Exception as err:
                        logger.warning(f"Failed to delete stale file {item.name}: {err}")
        if count > 0:
            logger.info(f"Cleaned up {count} expired temporary file(s).")
    except Exception as e:
        logger.error(f"Error during stale file cleanup: {e}")

async def start_periodic_cleaner(interval_seconds: int = 300):
    """Background task to clean up old temp files periodically."""
    while True:
        try:
            cleanup_stale_files()
        except Exception as e:
            logger.error(f"Unexpected error in periodic cleaner: {e}")
        await asyncio.sleep(interval_seconds)
