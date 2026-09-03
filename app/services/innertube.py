"""
YouTube InnerTube client helpers.

ANDROID_VR often returns:
  - lengthSeconds (duration)
  - progressive muxed MP4 URLs (itag 18) without signature cipher

This works better on cloud hosts than public Invidious mirrors.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from app.services.external_streams import extract_youtube_id, looks_like_media, _safe_filename

logger = logging.getLogger("downloader.innertube")

# Public InnerTube key used by official clients (not a secret API key)
_INNERTUBE_KEY = "AIzaSyA8eiZmM1FaDVjRy-df2KTyQ_vz_yYM39w"

_CLIENTS = [
    {
        "name": "ANDROID_VR",
        "version": "1.60.19",
        "ua": "com.google.android.apps.youtube.vr.oculus/1.60.19 (Linux; U; Android 12) gzip",
        "extra": {},
    },
    {
        "name": "TVHTML5",
        "version": "7.20241001.08.00",
        "ua": "Mozilla/5.0 (ChromiumStylePlatform) Cobalt/Version",
        "extra": {},
    },
    {
        "name": "WEB",
        "version": "2.20241121.01.00",
        "ua": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "extra": {},
    },
]


async def fetch_player(video_id: str) -> Optional[Dict[str, Any]]:
    """Return first successful player JSON for video_id."""
    timeout = httpx.Timeout(25.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for c in _CLIENTS:
            body = {
                "context": {
                    "client": {
                        "clientName": c["name"],
                        "clientVersion": c["version"],
                        "hl": "en",
                        "gl": "US",
                        **c["extra"],
                    }
                },
                "videoId": video_id,
                "contentCheckOk": True,
                "racyCheckOk": True,
            }
            try:
                r = await client.post(
                    f"https://www.youtube.com/youtubei/v1/player?key={_INNERTUBE_KEY}&prettyPrint=false",
                    json=body,
                    headers={
                        "User-Agent": c["ua"],
                        "Content-Type": "application/json",
                    },
                )
                if r.status_code >= 400:
                    continue
                data = r.json()
                status = (data.get("playabilityStatus") or {}).get("status")
                if status and status not in {"OK", "LIVE_STREAM_OFFLINE"}:
                    # still may have videoDetails
                    pass
                if data.get("videoDetails") or data.get("streamingData"):
                    data["_client"] = c["name"]
                    logger.info("InnerTube hit client=%s video=%s", c["name"], video_id)
                    return data
            except Exception as exc:
                logger.debug("InnerTube %s failed: %s", c["name"], exc)
    return None


def _meta_from_player(data: Dict[str, Any]) -> Dict[str, Any]:
    vd = data.get("videoDetails") or {}
    out: Dict[str, Any] = {}
    if vd.get("lengthSeconds"):
        try:
            out["duration"] = int(vd["lengthSeconds"])
        except Exception:
            pass
    if vd.get("title"):
        out["title"] = vd["title"]
    if vd.get("author"):
        out["uploader"] = vd["author"]
    if vd.get("viewCount"):
        try:
            out["view_count"] = int(vd["viewCount"])
        except Exception:
            pass
    thumbs = ((vd.get("thumbnail") or {}).get("thumbnails")) or []
    if thumbs:
        out["thumbnail"] = thumbs[-1].get("url")
    return out


async def fetch_innertube_meta(url: str) -> Dict[str, Any]:
    video_id = extract_youtube_id(url)
    if not video_id:
        return {}
    data = await fetch_player(video_id)
    if not data:
        return {}
    return _meta_from_player(data)


def _height_from_format(fmt: Dict[str, Any]) -> int:
    q = str(fmt.get("qualityLabel") or fmt.get("quality") or "")
    m = re.search(r"(\d+)", q)
    if m:
        return int(m.group(1))
    return int(fmt.get("height") or 0)


async def resolve_via_innertube(
    page_url: str,
    format_type: str = "video",
    quality: str = "720p",
    require_probe: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    Resolve a progressive playable media URL via InnerTube.
    Prefers muxed formats (itag 18 etc.) so Windows can play the file.
    """
    video_id = extract_youtube_id(page_url)
    if not video_id:
        return None

    data = await fetch_player(video_id)
    if not data:
        return None

    streaming = data.get("streamingData") or {}
    progressive: List[Dict[str, Any]] = list(streaming.get("formats") or [])
    progressive = [f for f in progressive if f.get("url")]

    target = 720
    try:
        target = int(re.sub(r"\D", "", quality) or "720")
    except Exception:
        target = 720

    if format_type == "audio":
        adaptive = [
            f for f in (streaming.get("adaptiveFormats") or [])
            if f.get("url") and str(f.get("mimeType") or "").startswith("audio/")
        ]
        adaptive.sort(key=lambda f: int(f.get("bitrate") or 0), reverse=True)
        chosen = adaptive[0] if adaptive else None
        ext = "m4a"
        content_type = "audio/mp4"
    else:
        mp4 = [f for f in progressive if "mp4" in str(f.get("mimeType") or "")]
        mp4.sort(
            key=lambda f: (
                -(1 if _height_from_format(f) <= target else 0),
                -_height_from_format(f),
            )
        )
        chosen = mp4[0] if mp4 else (progressive[0] if progressive else None)
        ext = "mp4"
        content_type = "video/mp4"

    if not chosen or not chosen.get("url"):
        return None

    stream_url = chosen["url"]
    if require_probe:
        try:
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                probe = await client.get(
                    stream_url,
                    headers={"Range": "bytes=0-1023", "User-Agent": "Mozilla/5.0"},
                )
                if probe.status_code >= 400 or not looks_like_media(probe.content):
                    logger.warning("InnerTube URL probe failed for %s", video_id)
                    if probe.status_code >= 400:
                        return None
        except Exception as exc:
            logger.warning("InnerTube probe error: %s", exc)
            return None

    qlabel = chosen.get("qualityLabel") or quality or "360p"
    return {
        "url": stream_url,
        "provider": f"innertube:{data.get('_client', 'unknown')}",
        "filename": _safe_filename(video_id, str(qlabel), ext),
        "ext": ext,
        "content_type": content_type,
        "itag": chosen.get("itag"),
    }
