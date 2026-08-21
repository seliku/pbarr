"""
MediathekViewWeb - the shared index of the German-language public broadcasters.

Covers ARD, ZDF, 3sat, arte, BR, MDR, NDR, WDR, ORF, SRF and the rest in one
query, which is why a single module reaches almost all of them.

Serves as the reference implementation of MediathekSource: a connector for
another country needs to do exactly what this file does - ask its broadcaster
what exists under a name, and hand the answers over as MediaItem.
"""

import json
import re
import logging
from datetime import datetime, timezone
from typing import List

import httpx

from app.modules.sources.base import MediathekSource, MediaItem

logger = logging.getLogger(__name__)


# Wie die deutschsprachigen Sender ihre Nummerierung in den Titel schreiben,
# z. B. "Folge 104: Ausgebrannt (S07/E04)". Nur eindeutige Formen werden gelesen.
#
# Bewusst NICHT erkannt: eine blosse Zahl in Klammern wie "(44)" - das ist eine
# fortlaufende Zaehlung ueber alle Staffeln - und ein Teilungshinweis wie "(1/2)".
# Daraus eine Staffel-Folge-Nummer zu raten, ergaebe falsche Dateinamen.
#
# Diese Muster gehoeren hierher und nicht in den Kern: wo ein Sender seine
# Nummerierung hinschreibt und in welcher Sprache, ist Landessache. Ein
# spanisches Modul bringt seine eigenen mit, und der Kern muss davon nichts wissen.
_EPISODE_PATTERNS = [
    re.compile(r"\bS(\d{1,2})\s*[/\-_ ]?\s*E(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"\bStaffel\s*(\d{1,2})\b.*?\bFolge\s*(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"\bSeason\s*(\d{1,2})\b.*?\bEpisode\s*(\d{1,3})\b", re.IGNORECASE),
]


def _lies_nummer(titel, beschreibung):
    """Staffel und Folge aus dem Titel lesen, sonst (None, None)."""
    text = f"{titel or ''} {beschreibung or ''}"
    for muster in _EPISODE_PATTERNS:
        treffer = muster.search(text)
        if treffer:
            try:
                return int(treffer.group(1)), int(treffer.group(2))
            except (TypeError, ValueError):
                continue
    return None, None


class MediathekViewWebSource(MediathekSource):
    name = "mediathekviewweb"
    description = "Gemeinsamer Index der deutschsprachigen Mediatheken"
    country = "DE"
    version = "2.0.0"

    # Barrierefreiheits-Fassungen der deutschsprachigen Sender.
    default_exclude = "klare Sprache,Audiodeskription,Gebärdensprache"

    # ae/oe/ue/ss haben keine Unicode-Zerlegung, die der Kern falten koennte.
    key_translit = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}

    API = "https://mediathekviewweb.de/api/query"

    def __init__(self, timeout: float = 30.0, page_size: int = 150):
        self.timeout = timeout
        self.page_size = page_size

    async def search(self, topic: str) -> List[MediaItem]:
        body = {
            "queries": [{"fields": ["topic"], "query": topic}],
            "sortBy": "timestamp",
            "sortOrder": "desc",
            "future": False,
            "offset": 0,
            "size": self.page_size,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    self.API,
                    content=json.dumps(body),
                    # The API insists on text/plain despite taking JSON.
                    headers={"Content-Type": "text/plain"},
                )

            if resp.status_code != 200:
                logger.warning(f"MediathekViewWeb: HTTP {resp.status_code} fuer '{topic}'")
                return []

            results = (resp.json().get("result") or {}).get("results") or []

        except Exception as e:
            logger.warning(f"MediathekViewWeb nicht erreichbar fuer '{topic}': {e}")
            return []

        items = [self._to_item(raw) for raw in results]
        items = [i for i in items if i is not None]
        logger.info(f"  {self.name}: {len(items)} Treffer fuer '{topic}'")
        return items

    def _to_item(self, raw: dict):
        """Turn one API result into a MediaItem, or None when unusable."""
        urls = {
            "hd": raw.get("url_video_hd") or "",
            "normal": raw.get("url_video") or "",
            "low": raw.get("url_video_low") or "",
        }
        urls = {k: v for k, v in urls.items() if v}
        if not urls:
            return None

        ts = raw.get("timestamp")
        aired = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None

        # Die Schnittstelle nennt keine Nummerierung, die Sender schreiben sie
        # aber in den Titel.
        staffel, folge = _lies_nummer(raw.get("title"), raw.get("description"))

        return MediaItem(
            source=self.name,
            # MediathekViewWeb has no stable id of its own, so the video URL
            # carries the identity.
            source_id=urls.get("normal") or urls.get("hd") or urls.get("low"),
            topic=raw.get("topic") or "",
            title=raw.get("title") or "",
            description=raw.get("description") or "",
            channel=raw.get("channel") or "",
            aired=aired,
            duration_seconds=raw.get("duration"),
            urls=urls,
            season=staffel,
            episode=folge,
        )
