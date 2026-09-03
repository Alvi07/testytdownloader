import os
import re
import uuid
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
import httpx
from urllib.parse import quote

from app.config import (
    APP_TITLE,
    APP_DESCRIPTION,
    STATIC_DIR,
    DOWNLOADS_DIR,
    COOKIES_FILE,
    PROXY_URL,
)
from app.services.downloader import get_video_info, download_media
from app.services.external_streams import (
    resolve_external_download,
    extract_youtube_id,
    collect_youtube_candidates,
    media_request_headers,
)
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
    Download media and force a local browser save.

    YouTube (cloud-friendly):
      Try Piped proxy → InnerTube → Invidious (each until media bytes succeed),
      then yt-dlp last.
    """
    if not is_valid_url(url):
        raise HTTPException(status_code=400, detail="Invalid target URL.")

    from app.services.external_streams import looks_like_media, normalize_quality

    quality = normalize_quality(quality, format_type)
    direct_error = "Download failed."
    is_youtube = bool(extract_youtube_id(url))

    async def try_candidate(external: dict) -> Optional[FileResponse]:
        stream_url = external["url"]
        provider = external.get("provider") or "external"

        ext = (external.get("ext") or "mp4").lstrip(".")
        filename = sanitize_download_name(
            external.get("filename") or f"video_{quality}.{ext}"
        )
        if not filename.lower().endswith(f".{ext}"):
            filename = f"{filename.rsplit('.', 1)[0]}.{ext}"
        media_type = external.get("content_type") or (
            "audio/mp4" if format_type == "audio" else "video/mp4"
        )

        logger.info("Trying download via %s for %s", provider, url)
        temp_path = DOWNLOADS_DIR / f"ext_{uuid.uuid4().hex[:12]}.{ext}"

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(180.0, connect=20.0),
            follow_redirects=True,
        ) as client:
            async with client.stream(
                "GET", stream_url, headers=media_request_headers(stream_url)
            ) as upstream:
                if upstream.status_code >= 400:
                    raise RuntimeError(f"{provider} HTTP {upstream.status_code}")
                first = b""
                total = 0
                with open(temp_path, "wb") as out:
                    async for chunk in upstream.aiter_bytes(64 * 1024):
                        if not first:
                            first = chunk[:64]
                            if not looks_like_media(first):
                                raise RuntimeError(f"{provider} returned non-media data")
                        out.write(chunk)
                        total += len(chunk)

        if total < 10_000:
            temp_path.unlink(missing_ok=True)
            raise RuntimeError(f"{provider} file too small ({total} bytes)")

        background_tasks.add_task(delete_temp_file, str(temp_path))
        return FileResponse(
            path=str(temp_path),
            filename=filename,
            media_type=media_type,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{filename}"; '
                    f"filename*=UTF-8''{quote(filename)}"
                ),
                "Access-Control-Expose-Headers": (
                    "Content-Disposition, X-Download-Mode, X-Download-Provider"
                ),
                "X-Download-Mode": "external-proxy",
                "X-Download-Provider": provider,
                "Cache-Control": "no-store",
            },
        )

    # YouTube: try every mirror candidate until one yields a real MP4
    if is_youtube:
        candidates = await collect_youtube_candidates(url, format_type, quality)
        if not candidates:
            logger.warning("No YouTube candidates resolved for %s", url)
        for cand in candidates:
            try:
                resp = await try_candidate(cand)
                if resp is not None:
                    return resp
            except Exception as ext_err:
                logger.error("Candidate %s failed: %s", cand.get("provider"), ext_err)
                direct_error = str(ext_err)

    # yt-dlp path
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
                "Access-Control-Expose-Headers": (
                    "Content-Disposition, X-Download-Mode, X-Download-Provider"
                ),
                "X-Download-Mode": "direct",
            },
        )
    except Exception as e:
        logger.warning("yt-dlp download failed for %s: %s", url, e)
        direct_error = str(e)

    raise HTTPException(
        status_code=403 if is_youtube else 500,
        detail=(
            "YouTube blocked server download and no working mirror was found. "
            "Try again later, or run the app locally."
            if is_youtube
            else f"Download failed: {direct_error}"
        ),
    )

def sanitize_download_name(name: str) -> str:
    """Keep filenames safe for Content-Disposition and always keep a media extension."""
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", (name or "").strip())
    cleaned = cleaned.replace("undefined", "720p").replace("null", "720p")
    cleaned = cleaned.strip(" ._") or "download"
    if not re.search(r"\.(mp4|m4a|mp3|webm)$", cleaned, re.I):
        cleaned = f"{cleaned}.mp4"
    return cleaned[:180]


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
