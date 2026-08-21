"""
Direct Mediathek path - no Sonarr, no TVDB.

Why this exists
---------------
The original design looked up a show in TVDB, asked Sonarr which episodes it
was missing, and downloaded a Mediathek item only when both agreed on the same
season/episode pair. In practice they never agreed: pbarr and Sonarr query TVDB
independently and end up with different numbering, and many public broadcasting
shows are not in TVDB at all. The result was zero downloads.

This module drops the numbering entirely. A watchlist entry is just a topic
name plus filters. Whatever the Mediathek offers under that topic and passes the
filters gets fetched, named by its broadcast date. Plex reads date-based
episodes natively, so no episode numbers are needed anywhere.

Identity of an item is its source URL - the only field that stays stable across
Mediathek API responses.
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import text

logger = logging.getLogger(__name__)

MVW_API = "https://mediathekviewweb.de/api/query"

# quality preference -> API field, in fallback order
QUALITY_FIELDS = {
    "hd":     ("url_video_hd", "url_video", "url_video_low"),
    "normal": ("url_video", "url_video_hd", "url_video_low"),
    "low":    ("url_video_low", "url_video", "url_video_hd"),
}

# characters that are unsafe or annoying in file names
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_SPACES = re.compile(r"\s+")


class MediathekDirect:
    """Fetches items straight from MediathekViewWeb."""

    def __init__(self, library_path: str = "/app/library", timeout: float = 30.0):
        self.library_path = Path(library_path)
        self.timeout = timeout

    # ------------------------------------------------------------------ search

    async def search(self, topic: str, size: int = 150) -> list:
        """
        Query MediathekViewWeb for everything published under a topic.

        Returns the raw result list, newest first. An empty list means either
        no hits or an unreachable API - the caller must not treat that as
        "nothing exists any more" and delete things. We learned that lesson.
        """
        body = {
            "queries": [{"fields": ["topic"], "query": topic}],
            "sortBy": "timestamp",
            "sortOrder": "desc",
            "future": False,
            "offset": 0,
            "size": size,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    MVW_API,
                    content=json.dumps(body),
                    headers={"Content-Type": "text/plain"},
                )
            if resp.status_code != 200:
                logger.warning(
                    f"MediathekViewWeb returned HTTP {resp.status_code} for topic '{topic}'"
                )
                return []
            data = resp.json()
            results = (data.get("result") or {}).get("results") or []
            logger.info(f"  MediathekViewWeb: {len(results)} Treffer fuer '{topic}'")
            return results
        except Exception as e:
            logger.warning(f"MediathekViewWeb unreachable for topic '{topic}': {e}")
            return []

    # ----------------------------------------------------------------- filters

    @staticmethod
    def passes_filters(item: dict, min_minutes: int, max_minutes: int,
                       exclude_keywords: str, include_senders: str) -> tuple:
        """
        Check one item against a watchlist entry's filters.

        Returns (True, "") when it passes, (False, reason) otherwise. The reason
        is logged at debug level so it is possible to see why something was
        skipped without guessing.
        """
        duration_min = (item.get("duration") or 0) / 60

        if min_minutes and duration_min < min_minutes:
            return False, f"zu kurz ({duration_min:.0f} < {min_minutes} min)"
        if max_minutes and duration_min > max_minutes:
            return False, f"zu lang ({duration_min:.0f} > {max_minutes} min)"

        haystack = f"{item.get('title', '')} {item.get('description', '')}".lower()
        for word in (w.strip().lower() for w in (exclude_keywords or "").split(",")):
            if word and word in haystack:
                return False, f"Ausschlusswort '{word}'"

        senders = [s.strip().lower() for s in (include_senders or "").split(",") if s.strip()]
        if senders and (item.get("channel") or "").lower() not in senders:
            return False, f"Sender '{item.get('channel')}' nicht in Auswahl"

        return True, ""

    # ----------------------------------------------------------------- quality

    @staticmethod
    def pick_stream(item: dict, quality: str = "hd") -> tuple:
        """
        Pick a stream URL for the wanted quality, falling back if it is missing.

        Returns (url, actual_quality) or (None, None) when the item carries no
        usable video URL at all.
        """
        order = QUALITY_FIELDS.get((quality or "hd").lower(), QUALITY_FIELDS["hd"])
        names = {"url_video_hd": "hd", "url_video": "normal", "url_video_low": "low"}
        for field in order:
            url = item.get(field)
            if url:
                return url, names[field]
        return None, None

    # ------------------------------------------------------------------ naming

    @classmethod
    def sanitize(cls, text_value: str) -> str:
        """Strip characters that do not belong in a file name."""
        cleaned = _UNSAFE.sub("", text_value or "")
        cleaned = _SPACES.sub(" ", cleaned).strip(" .")
        return cleaned[:150] or "Unbenannt"

    def build_path(self, show_name: str, item: dict) -> Path:
        """
        Build the target path in the layout Plex expects for date-based shows:

            <library>/<Show>/Season <YYYY>/<Show> - <YYYY-MM-DD> - <Title>.<ext>

        Plex reads YYYY-MM-DD in place of SxxEyy, which is exactly why this
        works without any episode numbering.
        """
        ts = item.get("timestamp")
        aired = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(timezone.utc)

        show = self.sanitize(show_name)
        title = self.sanitize(item.get("title") or "Ohne Titel")
        url = item.get("url_video") or item.get("url_video_hd") or ""
        ext = Path(url.split("?")[0]).suffix or ".mp4"

        filename = f"{show} - {aired:%Y-%m-%d} - {title}{ext}"
        return self.library_path / show / f"Season {aired:%Y}" / filename

    # ---------------------------------------------------------------- download

    async def download(self, url: str, target: Path) -> int:
        """
        Stream a file to disk. Returns the byte count, or 0 on failure.

        Downloads to a .part file first and renames on success, so an aborted
        run never leaves a half file that looks complete to Plex.
        """
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_suffix(target.suffix + ".part")
        written = 0
        try:
            async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
                async with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        logger.warning(f"    Download fehlgeschlagen: HTTP {resp.status_code}")
                        return 0
                    with open(part, "wb") as fh:
                        async for chunk in resp.aiter_bytes(chunk_size=1 << 20):
                            fh.write(chunk)
                            written += len(chunk)
            part.rename(target)
            return written
        except Exception as e:
            logger.warning(f"    Download abgebrochen: {e}")
            part.unlink(missing_ok=True)
            return 0
