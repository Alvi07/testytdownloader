import asyncio
import uuid
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

import yt_dlp

from app.config import DOWNLOADS_DIR, DEFAULT_USER_AGENT, COOKIES_FILE, PROXY_URL
from app.utils.helpers import (
    format_bytes,
    format_duration,
    format_count,
    sanitize_filename,
)
from app.services.external_streams import extract_youtube_id

logger = logging.getLogger("downloader.service")


# ---------------------------------------------------------------------------
# Base yt-dlp configuration
# ---------------------------------------------------------------------------

BASE_YTDL_OPTS: Dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    "geo_bypass": True,
    "socket_timeout": 60,
    "retries": 10,
    "fragment_retries": 10,
    "file_access_retries": 5,
    "concurrent_fragment_downloads": 1,
    # YouTube JS challenge solver
    "js_runtimes": {"deno": {}},
    "remote_components": ["ejs:github"],
    # android/ios/mweb work on cloud; "default"/web often: "Failed to extract any player response"
    "extractor_args": {
        "youtube": {
            "player_client": ["android", "ios", "mweb", "tv", "web"],
        }
    },
    "http_headers": {
        "Referer": "https://www.youtube.com/",
        "Origin": "https://www.youtube.com",
    },
}


def _build_ydl_opts(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Merge base opts with optional extras and cookies file when available."""
    opts: Dict[str, Any] = {**BASE_YTDL_OPTS, **(extra or {})}
    # Deep-copy nested dicts so callers can safely mutate per attempt
    if "extractor_args" in opts:
        opts["extractor_args"] = {
            k: (dict(v) if isinstance(v, dict) else v)
            for k, v in opts["extractor_args"].items()
        }
    if "http_headers" in opts:
        opts["http_headers"] = dict(opts["http_headers"])

    if COOKIES_FILE is not None:
        opts["cookiefile"] = str(COOKIES_FILE)
        # Custom UA + browser cookies often triggers YouTube bot checks on download
        opts.pop("user_agent", None)
    else:
        opts["user_agent"] = DEFAULT_USER_AGENT

    if PROXY_URL:
        opts["proxy"] = PROXY_URL

    return opts


def _is_bot_block_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "not a bot" in msg
        or "use --cookies" in msg
        or "sign in to confirm" in msg
        or "cookies are no longer valid" in msg
    )


def _is_retryable_download_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        _is_bot_block_error(exc)
        or "format is not available" in msg
        or "http error 403" in msg
        or "403: forbidden" in msg
        or "unable to download video data" in msg
    )


# ---------------------------------------------------------------------------
# Extract video information
# ---------------------------------------------------------------------------

def _extract_info_sync(url: str) -> Dict[str, Any]:
    """Synchronously extract metadata using yt-dlp without downloading."""

    client_attempts = [
        ["android", "ios", "mweb", "tv", "web"],
        ["android", "ios"],
        ["mweb", "web"],
        ["tv"],
    ]
    last_err: Optional[Exception] = None

    for clients in client_attempts:
        ydl_opts = _build_ydl_opts({
            "extract_flat": False,
            "skip_download": True,
            "ignore_no_formats_error": True,
            "extractor_args": {
                "youtube": {"player_client": clients},
            },
        })
        ydl_opts.pop("format", None)
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    raise ValueError("Could not extract information from the provided URL.")
                return ydl.sanitize_info(info)
        except Exception as exc:
            last_err = exc
            logger.warning("yt-dlp info failed clients=%s: %s", clients, exc)

    raise last_err or ValueError("Could not extract information from the provided URL.")


def _standard_quality_options() -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """UI quality cards when only metadata is available (no yt-dlp formats)."""
    video_options = [
        {
            "height": res,
            "resolution": f"{res}p",
            "ext": "mp4",
            "filesize": None,
            "filesize_formatted": "High Quality",
            "quality_tag": "Full HD" if res >= 1080 else ("HD" if res >= 720 else "SD"),
        }
        for res in (1080, 720, 480, 360)
    ]
    audio_options = [
        {
            "format_key": "mp3_320",
            "title": "MP3 Audio (High Quality)",
            "ext": "mp3",
            "bitrate": "320 kbps",
            "filesize_formatted": "Universal Audio",
        },
        {
            "format_key": "mp3_192",
            "title": "MP3 Audio (Standard)",
            "ext": "mp3",
            "bitrate": "192 kbps",
            "filesize_formatted": "Compact Audio",
        },
        {
            "format_key": "m4a_best",
            "title": "M4A Audio (Original Quality)",
            "ext": "m4a",
            "bitrate": "Original Stream",
            "filesize_formatted": "Original Quality",
        },
    ]
    return video_options, audio_options


async def get_youtube_info_fallback(url: str) -> Dict[str, Any]:
    """Simple YouTube analyze without yt-dlp (InnerTube / Piped)."""
    from app.services.metadata_enrich import fetch_youtube_duration_and_meta

    video_id = extract_youtube_id(url)
    if not video_id:
        raise ValueError("Not a YouTube URL.")

    meta = await fetch_youtube_duration_and_meta(url)
    if not meta.get("title") and not meta.get("duration"):
        raise ValueError("Could not analyze this YouTube video via fallback.")

    duration_sec = int(meta.get("duration") or 0)
    title = meta.get("title") or "YouTube Video"
    thumbnail = meta.get("thumbnail") or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    uploader = meta.get("uploader") or "YouTube"
    view_count = meta.get("view_count")
    video_options, audio_options = _standard_quality_options()

    return {
        "title": title,
        "thumbnail": thumbnail,
        "duration": duration_sec,
        "duration_formatted": format_duration(duration_sec),
        "uploader": uploader,
        "view_count": view_count,
        "view_count_formatted": format_count(view_count) if view_count else "0",
        "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
        "description": "",
        "video_options": video_options,
        "audio_options": audio_options,
        "source": "fallback",
    }


async def get_video_info(url: str) -> Dict[str, Any]:
    """Async wrapper to fetch and parse video metadata and formats."""

    loop = asyncio.get_running_loop()
    raw_info: Optional[Dict[str, Any]] = None
    extract_error: Optional[Exception] = None

    try:
        raw_info = await loop.run_in_executor(None, _extract_info_sync, url)
    except Exception as exc:
        extract_error = exc
        logger.warning("yt-dlp analyze failed for %s: %s", url, exc)
        if extract_youtube_id(url):
            logger.info("Using simple YouTube fallback for analyze: %s", url)
            return await get_youtube_info_fallback(url)
        raise

    if not raw_info:
        if extract_youtube_id(url):
            return await get_youtube_info_fallback(url)
        raise ValueError(
            "Could not extract information from the provided URL."
        )

    title = raw_info.get(
        "title",
        "Untitled Video",
    )

    thumbnail = raw_info.get(
        "thumbnail",
        "",
    )

    if not thumbnail and raw_info.get("thumbnails"):
        thumbnails = raw_info.get(
            "thumbnails",
            [],
        )

        if thumbnails:
            thumbnail = thumbnails[-1].get(
                "url",
                "",
            )

    try:
        duration_sec = int(raw_info.get("duration") or 0)
    except Exception:
        duration_sec = 0

    uploader = (
        raw_info.get("uploader")
        or raw_info.get("channel")
        or raw_info.get("creator")
        or "Unknown Creator"
    )

    view_count = raw_info.get(
        "view_count"
    )

    webpage_url = raw_info.get(
        "webpage_url",
        url,
    )

    # Always enrich YouTube metadata when duration missing/zero
    if extract_youtube_id(url) and duration_sec <= 0:
        try:
            from app.services.metadata_enrich import fetch_youtube_duration_and_meta

            extra = await fetch_youtube_duration_and_meta(url)
            if extra.get("duration"):
                duration_sec = int(extra["duration"])
                logger.info("Enriched duration=%s for %s", duration_sec, url)
            if extra.get("title") and (not title or title == "Untitled Video"):
                title = extra["title"]
            if extra.get("uploader") and uploader == "Unknown Creator":
                uploader = extra["uploader"]
            if extra.get("thumbnail") and not thumbnail:
                thumbnail = extra["thumbnail"]
            if extra.get("view_count") and not view_count:
                view_count = extra["view_count"]
        except Exception as enrich_err:
            logger.warning("Metadata enrichment failed: %s", enrich_err)

    description = raw_info.get(
        "description",
        "",
    )

    if description and len(description) > 200:
        description = (
            description[:200]
            + "..."
        )

    # -----------------------------------------------------------------------
    # Parse formats
    # -----------------------------------------------------------------------

    formats = raw_info.get(
        "formats",
        []
    )

    video_qualities: Dict[
        int,
        Dict[str, Any]
    ] = {}

    audio_formats: List[
        Dict[str, Any]
    ] = []

    target_resolutions = [
        1080,
        720,
        480,
        360,
    ]

    for f in formats:

        height = f.get(
            "height"
        )

        vcodec = f.get(
            "vcodec",
            "none"
        )

        acodec = f.get(
            "acodec",
            "none"
        )

        ext = f.get(
            "ext",
            "mp4"
        )

        filesize = (
            f.get("filesize")
            or f.get("filesize_approx")
        )

        # -------------------------------------------------------------------
        # Audio-only stream
        # -------------------------------------------------------------------

        if (
            vcodec == "none"
            and acodec != "none"
        ):

            abr = f.get("abr") or 128

            audio_formats.append({
                "format_id": f.get(
                    "format_id"
                ),

                "ext": ext,

                "bitrate": (
                    f"{int(abr)} kbps"
                    if abr
                    else "Standard"
                ),

                "filesize": filesize,

                "filesize_formatted": (
                    format_bytes(filesize)
                    if filesize
                    else "Direct Extract"
                ),

                "acodec": acodec,
            })

        # -------------------------------------------------------------------
        # Video stream
        # -------------------------------------------------------------------

        if (
            height
            and height in target_resolutions
        ):

            if (
                height not in video_qualities
                or (
                    filesize
                    and not video_qualities[
                        height
                    ].get("filesize")
                )
            ):

                video_qualities[height] = {
                    "height": height,

                    "resolution": (
                        f"{height}p"
                    ),

                    "ext": "mp4",

                    "filesize": filesize,

                    "filesize_formatted": (
                        format_bytes(filesize)
                        if filesize
                        else "Estimated High Quality"
                    ),

                    "quality_tag": (
                        "Full HD"
                        if height >= 1080
                        else (
                            "HD"
                            if height >= 720
                            else "SD"
                        )
                    ),
                }

    # -----------------------------------------------------------------------
    # Ensure standard resolutions exist
    # -----------------------------------------------------------------------

    sorted_video_options = []

    for res in target_resolutions:

        quality_tag = (
            "Full HD"
            if res >= 1080
            else (
                "HD"
                if res >= 720
                else "SD"
            )
        )

        if res in video_qualities:

            sorted_video_options.append(
                video_qualities[res]
            )

        else:

            sorted_video_options.append({
                "height": res,

                "resolution": (
                    f"{res}p"
                ),

                "ext": "mp4",

                "filesize": None,

                "filesize_formatted": (
                    "High Quality"
                ),

                "quality_tag": quality_tag,
            })

    # -----------------------------------------------------------------------
    # Standard audio options
    # -----------------------------------------------------------------------

    standard_audio_options = [
        {
            "format_key": "mp3_320",
            "title": "MP3 Audio (High Quality)",
            "ext": "mp3",
            "bitrate": "320 kbps",
            "filesize_formatted": "Universal Audio",
        },
        {
            "format_key": "mp3_192",
            "title": "MP3 Audio (Standard)",
            "ext": "mp3",
            "bitrate": "192 kbps",
            "filesize_formatted": "Compact Audio",
        },
        {
            "format_key": "m4a_best",
            "title": "M4A Audio (Original Quality)",
            "ext": "m4a",
            "bitrate": "Original Stream",
            "filesize_formatted": "Original Quality",
        },
    ]

    # -----------------------------------------------------------------------
    # Return metadata
    # -----------------------------------------------------------------------

    return {
        "title": title,

        "thumbnail": thumbnail,

        "duration": duration_sec,

        "duration_formatted": (
            format_duration(
                duration_sec
            )
        ),

        "uploader": uploader,

        "view_count": view_count,

        "view_count_formatted": (
            format_count(
                view_count
            )
        ),

        "description": description,

        "webpage_url": webpage_url,

        "video_options": (
            sorted_video_options
        ),

        "audio_options": (
            standard_audio_options
        ),
    }


# ---------------------------------------------------------------------------
# Download media
# ---------------------------------------------------------------------------

def _download_sync(
    url: str,
    format_type: str,
    quality: str,
) -> Dict[str, Any]:
    """
    Synchronously download video/audio
    to a temporary file.
    """

    session_id = uuid.uuid4().hex[:10]

    out_template = str(
        DOWNLOADS_DIR
        / f"{session_id}_%(title)s.%(ext)s"
    )

    ydl_opts: Dict[str, Any] = _build_ydl_opts({
        "outtmpl": out_template,
    })

    target_ext = "mp4"

    content_type = "video/mp4"

    # -----------------------------------------------------------------------
    # AUDIO
    # -----------------------------------------------------------------------

    if format_type == "audio":

        # MP3
        if quality in (
            "mp3_320",
            "mp3_192",
            "mp3",
        ):

            bitrate = (
                "320"
                if quality == "mp3_320"
                else "192"
            )

            ydl_opts.update({

                "format": (
                    "bestaudio/best"
                ),

                "postprocessors": [
                    {
                        "key": (
                            "FFmpegExtractAudio"
                        ),

                        "preferredcodec": "mp3",

                        "preferredquality": bitrate,
                    }
                ],
            })

            target_ext = "mp3"

            content_type = "audio/mpeg"

        # M4A
        else:

            ydl_opts.update({

                "format": (
                    "bestaudio[ext=m4a]"
                    "/bestaudio/best"
                ),

                "postprocessors": [
                    {
                        "key": (
                            "FFmpegExtractAudio"
                        ),

                        "preferredcodec": "m4a",
                    }
                ],
            })

            target_ext = "m4a"

            content_type = "audio/mp4"

    # -----------------------------------------------------------------------
    # VIDEO
    # -----------------------------------------------------------------------

    else:

        try:

            height = int(
                quality.replace(
                    "p",
                    ""
                )
            )

        except Exception:

            height = 720


        ydl_opts.update({
            "format": (
                f"best[height<={height}][ext=mp4]/"
                f"best[height<={height}]/"
                f"bestvideo[height<={height}]+bestaudio/"
                "bestvideo+bestaudio/best"
            ),
            "merge_output_format": "mp4",
        })

        target_ext = "mp4"
        content_type = "video/mp4"

    # -----------------------------------------------------------------------
    # DOWNLOAD — try modern defaults first, then softer format fallbacks
    # Forced web/android clients often break cookies / cause CDN 403s.
    # -----------------------------------------------------------------------

    preferred_format = ydl_opts.get("format", "best")
    attempts: List[Dict[str, Any]] = [
        {
            "label": "android/ios progressive",
            "player_client": ["android", "ios", "mweb"],
            "format": "18/22/best[ext=mp4]/best",
        },
        {
            "label": "android/ios preferred",
            "player_client": ["android", "ios", "mweb", "tv", "web"],
            "format": preferred_format,
        },
        {
            "label": "mweb/web best",
            "player_client": ["mweb", "web"],
            "format": "best/bestvideo+bestaudio",
        },
        {
            "label": "ios m3u8 fallback",
            "player_client": ["ios", "mweb"],
            "format": (
                "bv*[protocol=m3u8_native]+ba*[protocol=m3u8_native]/"
                "b[protocol=m3u8_native]/best"
            ),
            "formats_missing_pot": True,
        },
    ]

    last_error: Optional[Exception] = None
    info: Optional[Dict[str, Any]] = None

    for attempt in attempts:
        attempt_opts = _build_ydl_opts({
            "outtmpl": out_template,
            "format": attempt["format"],
        })
        # preserve audio postprocessors / merge opts from primary config
        for key in ("postprocessors", "merge_output_format"):
            if key in ydl_opts:
                attempt_opts[key] = ydl_opts[key]

        youtube_args: Dict[str, Any] = {
            "player_client": attempt["player_client"],
        }
        if attempt.get("formats_missing_pot"):
            youtube_args["formats"] = ["missing_pot"]
        attempt_opts["extractor_args"] = {"youtube": youtube_args}

        try:
            logger.info("Download attempt: %s", attempt["label"])
            with yt_dlp.YoutubeDL(attempt_opts) as ydl:
                info = ydl.extract_info(url, download=True)
            if info:
                break
        except Exception as exc:
            last_error = exc
            logger.warning("Download attempt failed (%s): %s", attempt["label"], exc)
            if not _is_retryable_download_error(exc):
                raise
            continue

    if not info:
        if last_error:
            raise last_error
        raise RuntimeError("Download failed: no media returned.")

    raw_title = info.get("title", "download")
    sanitized_title = sanitize_filename(raw_title)


    # -----------------------------------------------------------------------
    # LOCATE DOWNLOADED FILE
    # -----------------------------------------------------------------------

    matching_files = list(
        DOWNLOADS_DIR.glob(
            f"{session_id}_*"
        )
    )


    if not matching_files:

        raise FileNotFoundError(
            "Download failed: output file not found."
        )


    final_file = matching_files[0]


    final_filename = (
        f"{sanitized_title}."
        f"{final_file.suffix.lstrip('.') or target_ext}"
    )


    return {
        "file_path": str(
            final_file
        ),

        "filename": final_filename,

        "content_type": content_type,
    }


# ---------------------------------------------------------------------------
# Async download wrapper
# ---------------------------------------------------------------------------

async def download_media(
    url: str,
    format_type: str,
    quality: str,
) -> Dict[str, Any]:
    """
    Async wrapper for media downloading.
    """

    loop = asyncio.get_running_loop()

    return await loop.run_in_executor(
        None,
        _download_sync,
        url,
        format_type,
        quality,
    )