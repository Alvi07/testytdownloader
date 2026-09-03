"""
External YouTube stream resolvers (Invidious / Piped).

Uses progressive (muxed audio+video) formats only so Windows players
can open the downloaded .mp4 file.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("downloader.external")

# Progressive muxed MP4 only (audio+video in one file).
# Do NOT use DASH video-only itags (137, 136, …) — they will not play alone.
_PROGRESSIVE_VIDEO_ITAGS = {
    1080: [37, 22, 18],  # 37 rarely available
    720: [22, 18],
    480: [59, 78, 18, 22],
    360: [18, 22],
}
_AUDIO_ITAGS = {
    "mp3_320": [140],
    "mp3_192": [140],
    "mp3": [140],
    "m4a_best": [140],
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


def normalize_quality(quality: Optional[str], format_type: str = "video") -> str:
    """Normalize quality labels; replace undefined/empty with safe defaults."""
    q = (quality or "").strip()
    if not q or q.lower() in {"undefined", "null", "none"}:
        return "720p" if format_type == "video" else "m4a_best"
    return q


def _quality_height(quality: str) -> int:
    q = normalize_quality(quality, "video")
    try:
        return int(re.sub(r"\D", "", q) or "720")
    except Exception:
        return 720


def _candidate_itags(format_type: str, quality: str) -> List[int]:
    if format_type == "audio":
        q = normalize_quality(quality, "audio")
        return list(_AUDIO_ITAGS.get(q, [140]))
    height = _quality_height(quality)
    for h in (1080, 720, 480, 360):
        if height >= h:
            return list(_PROGRESSIVE_VIDEO_ITAGS[h])
    return list(_PROGRESSIVE_VIDEO_ITAGS[360])


def _safe_filename(video_id: str, quality: str, ext: str = "mp4") -> str:
    q = normalize_quality(quality, "video")
    q = re.sub(r"[^\w.\-]+", "_", q).strip("_") or "720p"
    ext = (ext or "mp4").lstrip(".").lower()
    if ext not in {"mp4", "m4a", "webm", "mp3"}:
        ext = "mp4"
    return f"{video_id}_{q}.{ext}"


def _instance_list(env_key: str, defaults: List[str]) -> List[str]:
    raw = os.environ.get(env_key, "").strip()
    if raw:
        return [u.strip().rstrip("/") for u in raw.split(",") if u.strip()]
    return defaults


def looks_like_media(data: bytes) -> bool:
    """True if bytes look like MP4/WebM/M4A, not HTML/JSON error pages."""
    if not data or len(data) < 12:
        return False
    sample = data[:64].lstrip()
    lower = sample[:32].lower()
    if lower.startswith((b"<!doctype", b"<html", b"{", b"[")):
        return False
    # MP4 / M4A: ....ftyp
    if b"ftyp" in data[:64]:
        return True
    # WebM / Matroska
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return True
    # ID3 / MP3
    if data.startswith(b"ID3") or data[:2] == b"\xff\xfb":
        return True
    return False


async def _probe_media_url(client: httpx.AsyncClient, url: str) -> bool:
    """Confirm URL returns real media bytes (not HTML error)."""
    try:
        r = await client.get(url, headers={"Range": "bytes=0-1023"}, follow_redirects=True)
        if r.status_code >= 400:
            return False
        ctype = (r.headers.get("content-type") or "").lower()
        if "text/html" in ctype or "application/json" in ctype:
            return False
        return looks_like_media(r.content)
    except Exception:
        return False


async def resolve_via_invidious(
    video_id: str,
    format_type: str,
    quality: str,
) -> Optional[Dict[str, Any]]:
    instances = _instance_list("INVIDIOUS_INSTANCES", _DEFAULT_INVIDIOUS)
    itags = _candidate_itags(format_type, quality)
    # Always end with safest progressive fallbacks
    for fallback in (22, 18, 140):
        if fallback not in itags:
            itags.append(fallback)

    timeout = httpx.Timeout(15.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for base in instances:
            for itag in itags:
                url = f"{base}/latest_version?id={video_id}&itag={itag}"
                try:
                    ok = await _probe_media_url(client, url)
                except Exception as exc:
                    logger.debug("Invidious probe failed %s: %s", url, exc)
                    continue
                if not ok:
                    continue

                if format_type == "audio" or itag == 140:
                    ext = "m4a"
                else:
                    ext = "mp4"

                logger.info("Invidious hit: %s itag=%s", base, itag)
                return {
                    "url": url,
                    "provider": f"invidious:{urlparse(base).netloc}",
                    "filename": _safe_filename(video_id, quality, ext),
                    "itag": itag,
                    "ext": ext,
                    "content_type": "audio/mp4" if ext == "m4a" else "video/mp4",
                }
    return None


async def resolve_via_piped(
    video_id: str,
    format_type: str,
    quality: str,
) -> Optional[Dict[str, Any]]:
    """Fallback: Piped API — only progressive (non videoOnly) streams."""
    apis = _instance_list("PIPED_API_INSTANCES", _DEFAULT_PIPED)
    height = _quality_height(quality)
    timeout = httpx.Timeout(15.0, connect=8.0)

    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}) as client:
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
                streams = [
                    s for s in streams
                    if (s.get("mimeType") or "").startswith(("audio/mp4", "audio/m4a"))
                ]
                streams = sorted(streams, key=lambda s: s.get("bitrate") or 0, reverse=True)
                ext = "m4a"
            else:
                streams = data.get("videoStreams") or []
                # Progressive only = has audio already (not videoOnly)
                streams = [
                    s for s in streams
                    if not s.get("videoOnly")
                    and (s.get("mimeType") or "").startswith("video/mp4")
                ]

                def score(s: Dict[str, Any]) -> tuple:
                    q = str(s.get("quality") or s.get("qualityLabel") or "0")
                    digits = re.sub(r"\D", "", q) or "0"
                    h = int(digits)
                    return (-abs(h - height), h)

                streams = sorted(streams, key=score, reverse=True)
                ext = "mp4"

            for s in streams:
                stream_url = s.get("url")
                if not stream_url:
                    continue
                if not await _probe_media_url(client, stream_url):
                    continue
                logger.info("Piped hit: %s", api)
                return {
                    "url": stream_url,
                    "provider": f"piped:{urlparse(api).netloc}",
                    "filename": _safe_filename(video_id, quality, ext),
                    "ext": ext,
                    "content_type": "audio/mp4" if ext == "m4a" else "video/mp4",
                }
    return None


async def resolve_external_download(
    page_url: str,
    format_type: str = "video",
    quality: str = "720p",
) -> Optional[Dict[str, Any]]:
    """Resolve a playable progressive media URL for YouTube."""
    video_id = extract_youtube_id(page_url)
    if not video_id:
        return None

    quality = normalize_quality(quality, format_type)

    result = await resolve_via_invidious(video_id, format_type, quality)
    if result:
        return result

    result = await resolve_via_piped(video_id, format_type, quality)
    if result:
        return result

    logger.warning("No external stream resolver succeeded for %s", video_id)
    return None
