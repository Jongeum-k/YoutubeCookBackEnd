# app/utils/youtube.py

import re
from urllib.parse import parse_qs, urlparse

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

_PATH_PREFIXES = ("/shorts/", "/embed/", "/live/")


def extract_youtube_video_id(url: str) -> str | None:
    """Extract the 11-character video id from a YouTube URL.

    Supports youtube.com/watch?v=..., youtu.be/..., and the
    /shorts/, /embed/, /live/ path forms. Returns None if no valid
    video id can be found.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return None

    host = (parsed.hostname or "").lower()
    host = host.removeprefix("www.").removeprefix("m.")

    candidate: str | None = None

    if host == "youtu.be":
        candidate = parsed.path.lstrip("/").split("/")[0]

    elif host in {"youtube.com", "youtube-nocookie.com"}:
        if parsed.path == "/watch":
            values = parse_qs(parsed.query).get("v")
            candidate = values[0] if values else None
        else:
            for prefix in _PATH_PREFIXES:
                if parsed.path.startswith(prefix):
                    candidate = parsed.path[len(prefix):].split("/")[0]
                    break

    if candidate and _VIDEO_ID_RE.match(candidate):
        return candidate

    return None
