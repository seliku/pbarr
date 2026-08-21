"""
The contract every source module fulfils.

A source answers one question: "what does this broadcaster currently offer
under this name?" Everything after that - filtering, quality choice, naming,
downloading, remembering - is the core's job and identical for every country.

Deliberately NOT part of this contract:

  Season and episode numbers. Not every broadcaster numbers episodes, and the
  ones that do disagree with each other and with third-party databases. A
  source may fill them in when it genuinely knows them; the core falls back to
  reading them out of the title and then to the broadcast date, which every
  media server understands.

  Anything German. Channel names, quality labels and title conventions differ
  per country; a source normalises its own peculiarities and hands over plain
  data.

To add a broadcaster, drop a file into app/modules/sources/ that subclasses
MediathekSource and implements search(). Nothing else needs to change.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class MediaItem:
    """One programme a source can currently deliver."""

    # Where it came from and how to recognise it again. source_id should be
    # stable for the same programme across queries; when a broadcaster offers
    # nothing stable, use the video URL.
    source: str
    source_id: str

    # What it is
    topic: str                      # the show, as the broadcaster names it
    title: str                      # this particular programme
    description: Optional[str] = None
    channel: Optional[str] = None

    # When and how long
    aired: Optional[datetime] = None
    duration_seconds: Optional[int] = None

    # How to fetch it. Keys are quality labels the source chooses; the core
    # asks for "hd", "normal" or "low" and falls back through what is offered.
    urls: Dict[str, str] = field(default_factory=dict)

    # Only when the broadcaster states them itself. Leave empty otherwise -
    # guessing produces wrong file names.
    season: Optional[int] = None
    episode: Optional[int] = None

    def best_url(self, wanted: str = "hd") -> tuple:
        """Pick a URL for the wanted quality, falling back through the rest."""
        order = {
            "hd": ("hd", "normal", "low"),
            "normal": ("normal", "hd", "low"),
            "low": ("low", "normal", "hd"),
        }.get((wanted or "hd").lower(), ("hd", "normal", "low"))

        for quality in order:
            if self.urls.get(quality):
                return self.urls[quality], quality
        return None, None


class MediathekSource(ABC):
    """Base class for every broadcaster connector."""

    name: str = "unnamed"
    description: str = ""
    country: str = ""          # ISO code, purely informational
    version: str = "1.0.0"

    @abstractmethod
    async def search(self, topic: str) -> List[MediaItem]:
        """
        Everything currently on offer under this name.

        An empty list means "nothing found or not reachable" - the core never
        treats it as "this show no longer exists" and never deletes anything on
        the strength of it. Sources should log their own failures and return an
        empty list rather than raising.
        """
        raise NotImplementedError
