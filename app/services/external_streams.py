"""
External YouTube stream resolvers (Invidious / Piped).

Why: Free cloud hosts (Render) are often blocked by YouTube's CDN when
yt-dlp tries to pull media bytes. Public Invidious instances expose
`/latest_version` URLs on *their* domain — the user's browser downloads
from Invidious (not from Render → googlevideo), avoiding our cloud IP ban.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("downloader.external")

# Progressive itags (single-file MP4/M4A) — work with /latest_version
_VIDEO_ITAGS = {
    1080: [37, 137, 22, 18],  # prefer progressive when possible
    720: [22, 18],
    480: [59, 78, 18],
    360: [18, 22],
}
_AUDIO_ITAGS = {
    "mp3_320": [140, 251, 249, 250],
    "mp3_192": [140, 251, 249, 250],
    "mp3": [140, 251],
    "m4a_best": [140, 251],
}

_DEFAULT_INVIDIOUS = [
    "https://yewtu.be",
    "https://invidious.nerdvpn.de",
    "https://inv.nadeko.net",
    "https://invidious.projectsegfau.lt",
    "https://invidious.privacyredirect.com",
]

_DEFAULT_PIPED = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.adminforge.de",
    "https://pipedapi.nosebs.ru",
]


def extract_youtube_id(url: str) -> Optional[str]:
    """Extract 11-char YouTube video id from common URL shapes."""
    if not url:
        return None
    patterns = [
        r"(?:youtube\.com/watch\?(?:[^#]*&)?v=|youtube\.com/embed/|youtube\.com/shorts/|youtu\.be/)([A-Za-z0-9_-]{11})",
        r"youtube\.com/live/([A-Za-z0-9_-]{11})",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


def _quality_height(quality: str) -> int:
    try:
        return int(quality.replace("p", "").strip())
    except Exception:
        return 720


def _candidate_itags(format_type: str, quality: str) -> List[int]:
    if format_type == "audio":
        return list(_AUDIO_ITAGS.get(quality, [140, 251, 18]))
    height = _quality_height(quality)
    # pick nearest bucket
    for h in (1080, 720, 480, 360):
        if height >= h:
            return list(_VIDEO_ITAGS[h])
    return list(_VIDEO_ITAGS[360])


def _instance_list(env_key: str, defaults: List[str]) -> List[str]:
    raw = os.environ.get(env_key, "").strip()
    if raw:
        return [u.strip().rstrip("/") for u in raw.split(",") if u.strip()]
    return defaults


async def _head_ok(client: httpx.AsyncClient, url: str) -> bool:
    try:
        r = await client.head(url, follow_redirects=True)
        if r.status_code < 400:
            return True
        # some instances reject HEAD
        r = await client.get(url, headers={"Range": "bytes=0-1"}, follow_redirects=True)
        return r.status_code < 400
    except Exception:
        return False


async def resolve_via_invidious(
    video_id: str,
    format_type: str,
    quality: str,
) -> Optional[Dict[str, Any]]:
    instances = _instance_list("INVIDIOUS_INSTANCES", _DEFAULT_INVIDIOUS)
    itags = _candidate_itags(format_type, quality)
    timeout = httpx.Timeout(12.0, connect=6.0)

    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "ProStream/1.0"}) as client:
        for base in instances:
            for itag in itags:
                url = f"{base}/latest_version?id={video_id}&itag={itag}"
                try:
                    ok = await _head_ok(client, url)
                except Exception as exc:
                    logger.debug("Invidious check failed %s: %s", url, exc)
                    continue
                if not ok:
                    continue
                ext = "m4a" if format_type == "audio" and itag == 140 else ("webm" if itag in (251, 249, 250) else "mp4")
                logger.info("Invidious hit: %s itag=%s", base, itag)
                return {
                    "url": url,
                    "provider": f"invidious:{urlparse(base).netloc}",
                    "filename": f"{video_id}_{quality}.{ext}",
                    "itag": itag,
                }
    return None


async def resolve_via_piped(
    video_id: str,
    format_type: str,
    quality: str,
) -> Optional[Dict[str, Any]]:
    """Fallback: Piped API stream list (may return googlevideo URLs)."""
    apis = _instance_list("PIPED_API_INSTANCES", _DEFAULT_PIPED)
    height = _quality_height(quality)
    timeout = httpx.Timeout(15.0, connect=6.0)

    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "ProStream/1.0"}) as client:
        for api in apis:
            endpoint = f"{api}/streams/{video_id}"
            try:
                r = await client.get(endpoint)
                if r.status_code >= 400:
                    continue
                data = r.json()
            except Exception as exc:
                logger.debug("Piped failed %s: %s", api, exc)
                continue

            if format_type == "audio":
                streams = data.get("audioStreams") or []
                streams = sorted(streams, key=lambda s: s.get("bitrate") or 0, reverse=True)
            else:
                streams = data.get("videoStreams") or []
                # prefer mp4 progressive near requested height
                def score(s: Dict[str, Any]) -> tuple:
                    q = str(s.get("quality") or s.get("qualityLabel") or "0")
                    digits = re.sub(r"\D", "", q) or "0"
                    h = int(digits)
                    progressive = 1 if not s.get("videoOnly") else 0
                    mp4 = 1 if (s.get("mimeType") or "").startswith("video/mp4") else 0
                    return (progressive, mp4, -abs(h - height), h)

                streams = sorted(streams, key=score, reverse=True)

            for s in streams:
                stream_url = s.get("url")
                if not stream_url:
                    continue
                # Prefer proxied paths when present; still return googlevideo as last hope
                logger.info("Piped hit: %s", api)
                return {
                    "url": stream_url,
                    "provider": f"piped:{urlparse(api).netloc}",
                    "filename": f"{video_id}_{quality}.mp4",
                }
    return None


async def resolve_external_download(
    page_url: str,
    format_type: str = "video",
    quality: str = "720p",
) -> Optional[Dict[str, Any]]:
    """
    Resolve a browser-downloadable URL without pulling media through Render.
    """
    video_id = extract_youtube_id(page_url)
    if not video_id:
        return None

    # 1) Invidious /latest_version (best for free cloud — user hits Invidious domain)
    result = await resolve_via_invidious(video_id, format_type, quality)
    if result:
        return result

    # 2) Piped API
    result = await resolve_via_piped(video_id, format_type, quality)
    if result:
        return result

    logger.warning("No external stream resolver succeeded for %s", video_id)
    return None
