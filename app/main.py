import os
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, HttpUrl

from app.config import (
    APP_TITLE,
    APP_DESCRIPTION,
    STATIC_DIR,
    DOWNLOADS_DIR,
    COOKIES_FILE,
    PROXY_URL,
)
from app.services.downloader import get_video_info, download_media
from app.services.external_streams import resolve_external_download, extract_youtube_id
from app.services.cleaner import start_periodic_cleaner, cleanup_stale_files
from app.utils.helpers import is_valid_url

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for background tasks."""
    logger.info("Starting up downloader service...")
    if COOKIES_FILE:
        logger.info("YouTube cookies loaded from: %s", COOKIES_FILE)
    else:
        logger.warning(
            "No YouTube cookies found. Cloud hosts (Render) usually need "
            "COOKIES_FILE or YOUTUBE_COOKIES_BASE64 to avoid bot checks."
        )
    if PROXY_URL:
        # Do not log credentials — only scheme/host-ish hint
        safe = PROXY_URL.split("@")[-1] if "@" in PROXY_URL else PROXY_URL
        logger.info("Outbound proxy enabled for yt-dlp: %s", safe)
    else:
        logger.warning(
            "No YOUTUBE_PROXY/PROXY_URL set. Free Render IPs are often blocked "
            "by YouTube CDN for downloads; a residential proxy is recommended."
        )
    cleanup_stale_files()
    cleaner_task = asyncio.create_task(start_periodic_cleaner())
    yield
    logger.info("Shutting down downloader service...")
    cleaner_task.cancel()
    try:
        await cleaner_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title=APP_TITLE,
    description=APP_DESCRIPTION,
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request schemas
class VideoInfoRequest(BaseModel):
    url: str


def delete_temp_file(file_path: str):
    """Background task to remove temp file after client download completes."""
    try:
        path = Path(file_path)
        if path.exists():
            path.unlink(missing_ok=True)
            logger.info(f"Deleted downloaded file after transfer: {path.name}")
    except Exception as e:
        logger.warning(f"Failed to delete temp file {file_path}: {e}")


@app.get("/api/health")
async def health_check():
    """Health check endpoint for Render and uptime monitoring."""
    return {
        "status": "ok",
        "app": APP_TITLE,
        "version": "1.0.0",
        "cookies_loaded": COOKIES_FILE is not None,
        "proxy_configured": PROXY_URL is not None,
        "external_fallback": True,
    }


@app.post("/api/info")
async def fetch_info(payload: VideoInfoRequest):
    """Fetch video details, available qualities, and thumbnail preview."""
    url = payload.url.strip()
    if not is_valid_url(url):
        raise HTTPException(status_code=400, detail="Please enter a valid HTTP/HTTPS URL.")
    
    try:
        info = await get_video_info(url)
        return {"success": True, "data": info}
    except Exception as e:
        logger.error(f"Error fetching video info for {url}: {e}")
        error_msg = str(e)
        if "Video unavailable" in error_msg or "Private video" in error_msg:
            raise HTTPException(status_code=404, detail="The video is private, removed, or unavailable.")
        if "Sign in to confirm your age" in error_msg:
            raise HTTPException(status_code=403, detail="Age-restricted content cannot be retrieved directly.")
        if "not a bot" in error_msg.lower() or "Use --cookies" in error_msg:
            if COOKIES_FILE:
                detail = (
                    "YouTube still blocked this cloud request even with cookies. "
                    "Your cookies are likely expired/rotated. Export a FRESH cookies.txt "
                    "(logged into YouTube), convert to base64, update YOUTUBE_COOKIES_BASE64 "
                    "on Render, then redeploy/restart."
                )
            else:
                detail = (
                    "YouTube bot check blocked this request. "
                    "On Render, set YOUTUBE_COOKIES_BASE64 (or COOKIES_FILE) "
                    "with a fresh cookies.txt from a logged-in browser."
                )
            raise HTTPException(status_code=403, detail=detail)
        if "cookies are no longer valid" in error_msg.lower() or "rotated" in error_msg.lower():
            raise HTTPException(
                status_code=403,
                detail=(
                    "YouTube cookies are expired/rotated. Export fresh cookies from a "
                    "logged-in browser and update YOUTUBE_COOKIES_BASE64 on Render."
                ),
            )
        if "Requested format is not available" in error_msg or "Only images are available" in error_msg:
            raise HTTPException(
                status_code=503,
                detail=(
                    "YouTube stream formats could not be resolved on this server. "
                    "Redeploy with Deno/JS challenge support enabled, or try again shortly."
                ),
            )
        raise HTTPException(status_code=500, detail=f"Failed to analyze video: {error_msg}")


@app.get("/api/download")
async def download_file(
    background_tasks: BackgroundTasks,
    url: str = Query(..., description="Target Video or Media URL"),
    format_type: str = Query("video", pattern="^(video|audio)$"),
    quality: str = Query("720p", description="Quality format (e.g. 1080p, 720p, mp3_320, m4a_best)")
):
    """
    Download media.

    Strategy:
      1) Try yt-dlp on this server (works on home networks / unblocked IPs).
      2) If YouTube CDN/bot-blocks the cloud IP, resolve an Invidious/Piped
         URL and return JSON so the *browser* downloads it (Render never
         pulls googlevideo bytes).
    """
    if not is_valid_url(url):
        raise HTTPException(status_code=400, detail="Invalid target URL.")

    # --- Path A: direct yt-dlp on server ---
    try:
        result = await download_media(url, format_type, quality)
        file_path = result["file_path"]
        filename = result["filename"]
        content_type = result["content_type"]

        background_tasks.add_task(delete_temp_file, file_path)

        return FileResponse(
            path=file_path,
            filename=filename,
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Access-Control-Expose-Headers": "Content-Disposition",
                "X-Download-Mode": "direct",
            }
        )
    except Exception as e:
        logger.warning("Direct yt-dlp download failed for %s: %s", url, e)
        direct_error = str(e)

    # --- Path B: external resolver (browser-side download) ---
    if extract_youtube_id(url):
        try:
            external = await resolve_external_download(url, format_type, quality)
            if external and external.get("url"):
                logger.info(
                    "Using external download via %s for %s",
                    external.get("provider"),
                    url,
                )
                return JSONResponse(
                    {
                        "success": True,
                        "mode": "external",
                        "download_url": external["url"],
                        "filename": external.get("filename") or "video.mp4",
                        "provider": external.get("provider"),
                        "note": (
                            "Cloud IP was blocked by YouTube CDN; "
                            "opening an Invidious/Piped link in your browser instead."
                        ),
                    }
                )
        except Exception as ext_err:
            logger.error("External resolver failed for %s: %s", url, ext_err)

    # Both paths failed
    if (
        "not a bot" in direct_error.lower()
        or "Use --cookies" in direct_error
        or "Sign in to confirm" in direct_error
        or "HTTP Error 403" in direct_error
        or "403: Forbidden" in direct_error
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "YouTube blocked server download and no working Invidious/Piped "
                "mirror was found. Try again later, or run the app locally."
            ),
        )
    raise HTTPException(status_code=500, detail=f"Download failed: {direct_error}")


# Serve Frontend Static Assets
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
async def serve_frontend():
    """Serve the single-page application frontend."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return JSONResponse({
        "message": "Welcome to ProStream API. Frontend index.html not found.",
        "docs": "/docs"
    })
