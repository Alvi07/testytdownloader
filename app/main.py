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
)
from app.services.downloader import get_video_info, download_media
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
    return {"status": "ok", "app": APP_TITLE, "version": "1.0.0"}


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
        raise HTTPException(status_code=500, detail=f"Failed to analyze video: {error_msg}")


@app.get("/api/download")
async def download_file(
    background_tasks: BackgroundTasks,
    url: str = Query(..., description="Target Video or Media URL"),
    format_type: str = Query("video", pattern="^(video|audio)$"),
    quality: str = Query("720p", description="Quality format (e.g. 1080p, 720p, mp3_320, m4a_best)")
):
    """
    Download the requested video or audio file and stream it directly to the user.
    File is cleaned up immediately after transmission.
    """
    if not is_valid_url(url):
        raise HTTPException(status_code=400, detail="Invalid target URL.")
        
    try:
        result = await download_media(url, format_type, quality)
        file_path = result["file_path"]
        filename = result["filename"]
        content_type = result["content_type"]
        
        # Schedule cleanup after response finishes sending
        background_tasks.add_task(delete_temp_file, file_path)
        
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Access-Control-Expose-Headers": "Content-Disposition",
            }
        )
    except Exception as e:
        logger.error(f"Download error for {url}: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


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
