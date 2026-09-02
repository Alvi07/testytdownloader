import asyncio
import uuid
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

import yt_dlp

from app.config import DOWNLOADS_DIR, DEFAULT_USER_AGENT, COOKIES_FILE
from app.utils.helpers import (
    format_bytes,
    format_duration,
    format_count,
    sanitize_filename,
)

logger = logging.getLogger("downloader.service")


# ---------------------------------------------------------------------------
# Base yt-dlp configuration
# ---------------------------------------------------------------------------

BASE_YTDL_OPTS: Dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "user_agent": DEFAULT_USER_AGENT,
    "nocheckcertificate": True,
    "geo_bypass": True,
    "socket_timeout": 30,
    # Helps on some cloud IPs; cookies are still required on Render for YouTube
    "extractor_args": {
        "youtube": {
            "player_client": ["android", "web"],
        }
    },
}


def _build_ydl_opts(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Merge base opts with optional extras and cookies file when available."""
    opts: Dict[str, Any] = {**BASE_YTDL_OPTS, **(extra or {})}
    if COOKIES_FILE is not None:
        opts["cookiefile"] = str(COOKIES_FILE)
    return opts


# ---------------------------------------------------------------------------
# Extract video information
# ---------------------------------------------------------------------------

def _extract_info_sync(url: str) -> Dict[str, Any]:
    """Synchronously extract metadata using yt-dlp without downloading."""

    ydl_opts = _build_ydl_opts({
        "extract_flat": False,
        "skip_download": True,
    })

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(
            url,
            download=False,
        )

        return ydl.sanitize_info(info)


async def get_video_info(url: str) -> Dict[str, Any]:
    """Async wrapper to fetch and parse video metadata and formats."""

    loop = asyncio.get_running_loop()

    raw_info = await loop.run_in_executor(
        None,
        _extract_info_sync,
        url,
    )

    if not raw_info:
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

    duration_sec = raw_info.get(
        "duration",
        0,
    )

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
                f"bestvideo[height<={height}][ext=mp4]"
                "+bestaudio[ext=m4a]"
                f"/bestvideo[height<={height}]"
                "+bestaudio"
                f"/best[height<={height}]"
                "/best"
            ),

            "merge_output_format": "mp4",
        })

        target_ext = "mp4"

        content_type = "video/mp4"


    # -----------------------------------------------------------------------
    # DOWNLOAD
    # -----------------------------------------------------------------------

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:

        info = ydl.extract_info(
            url,
            download=True,
        )

        raw_title = info.get(
            "title",
            "download",
        )

        sanitized_title = sanitize_filename(
            raw_title
        )


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