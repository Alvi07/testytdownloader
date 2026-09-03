"""
Extra metadata helpers when yt-dlp returns incomplete info (e.g. duration=0).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

import httpx

from app.services.external_streams import extract_youtube_id

logger = logging.getLogger("downloader.metadata")

_PIPED_APIS = [
    "https://api.piped.private.coffee",
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.adminforge.de",
    "https://pipedapi.syncpundit.io",
]


async def fetch_youtube_duration_and_meta(url: str) -> Dict[str, Any]:
    """
    Best-effort enrichment for YouTube when yt-dlp omits duration.
    Order: InnerTube → Piped → watch-page scrape.
    """
    video_id = extract_youtube_id(url)
    if not video_id:
        return {}

    meta: Dict[str, Any] = {}

    # 1) InnerTube (reliable duration on cloud IPs)
    try:
        from app.services.innertube import fetch_innertube_meta

        meta = await fetch_innertube_meta(url)
        if meta.get("duration"):
            return meta
    except Exception as exc:
        logger.debug("InnerTube meta failed: %s", exc)

    # 2) Piped
    piped = await _from_piped(video_id)
    for k, v in piped.items():
        if v and not meta.get(k):
            meta[k] = v
    if meta.get("duration"):
        return meta

    # 3) Watch page scrape
    page = await _from_youtube_watch_page(video_id)
    for k, v in page.items():
        if v and not meta.get(k):
            meta[k] = v
    return meta


async def _from_piped(video_id: str) -> Dict[str, Any]:
    timeout = httpx.Timeout(12.0, connect=6.0)
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for api in _PIPED_APIS:
            try:
                r = await client.get(f"{api}/streams/{video_id}")
                if r.status_code != 200:
                    continue
                if "json" not in (r.headers.get("content-type") or ""):
                    continue
                data = r.json()
                duration = data.get("duration") or data.get("lengthSeconds")
                if not duration:
                    continue
                logger.info("Piped metadata hit %s duration=%s", api, duration)
                return {
                    "duration": int(duration),
                    "title": data.get("title"),
                    "uploader": data.get("uploader") or data.get("uploaderName"),
                    "thumbnail": data.get("thumbnailUrl") or data.get("thumbnail"),
                    "view_count": data.get("views") or data.get("viewCount"),
                }
            except Exception as exc:
                logger.debug("Piped meta failed %s: %s", api, exc)
    return {}


async def _from_youtube_watch_page(video_id: str) -> Dict[str, Any]:
    """Parse lengthSeconds from ytInitialPlayerResponse when available."""
    watch = f"https://www.youtube.com/watch?v={video_id}"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            r = await client.get(
                watch,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            if r.status_code >= 400:
                return {}
            html = r.text
    except Exception as exc:
        logger.debug("YouTube watch scrape failed: %s", exc)
        return {}

    out: Dict[str, Any] = {}
    m = re.search(r'"lengthSeconds"\s*:\s*"(\d+)"', html)
    if m:
        out["duration"] = int(m.group(1))
    m = re.search(r'"videoDetails"\s*:\s*\{[^}]*?"title"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', html)
    if m:
        try:
            out["title"] = bytes(m.group(1), "utf-8").decode("unicode_escape")
        except Exception:
            out["title"] = m.group(1)
    m = re.search(r'"viewCount"\s*:\s*"(\d+)"', html)
    if m:
        out["view_count"] = int(m.group(1))
    if out.get("duration"):
        logger.info("YouTube page metadata duration=%s", out["duration"])
    return out
