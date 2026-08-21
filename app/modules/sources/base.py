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


def is_stream(url: str) -> bool:
    """
    Ist die Adresse eine HLS-Abspielliste statt einer Datei?

    Teile der oeffentlich-rechtlichen Mediatheken liegen nur als Stream vor.
    Ohne diese Pruefung landet die Abspielliste selbst in der Bibliothek.
    """
    return (url or "").lower().split("?")[0].endswith((".m3u8", ".mpd"))


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

        # Eine echte Datei schlaegt eine Stream-Abspielliste, auch bei
        # geringerer Qualitaet. Wer eine .m3u8 speichert, legt eine 17 KB
        # grosse Textdatei unter einem Episodennamen ab - der Medienserver
        # zeigt eine Folge an, die sich nicht abspielen laesst.
        for quality in order:
            adresse = self.urls.get(quality)
            if adresse and not is_stream(adresse):
                return adresse, quality

        # Nur noch Streams uebrig. Wird zurueckgegeben, damit die Vorschau den
        # Grund nennen kann; der Download verweigert sie.
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

    # Woran dieser Sender seine Barrierefreiheits-Fassungen erkennt.
    #
    # Im deutschen Sprachraum sind das "Audiodeskription", "Gebaerdensprache"
    # und "klare Sprache" - anderswo heisst das anders. Der Kern kennt diese
    # Woerter nicht; er fragt hier nach und schlaegt sie beim Anlegen einer
    # Sendung als Ausschlussliste vor.
    default_exclude: str = ""

    # Zeichen, die beim Bilden des internen Schluessels ersetzt werden muessen.
    #
    # Der Kern faltet Akzente selbst (é wird e, ñ wird n) - das genuegt fuer die
    # meisten Sprachen. Zeichen ohne solche Zerlegung gehoeren hierher: im
    # Deutschen ae/oe/ue/ss, im Daenischen ae/oe/aa, und so fort.
    key_translit: dict = {}

    @abstractmethod
    async def search(self, topic: str) -> List[MediaItem]:
        """
        Everything currently on offer under this name.

        An empty list means "nothing found or not reachable" - the core never
        treats it as "this show no longer exists" and never deletes anything on
        the strength of it. Sources should log their own failures and return an
        empty list rather than raising.

        Reading season and episode numbers is the source's job, not the core's.
        Where a broadcaster puts them, and in which language, is a local matter:
        German broadcasters write "Folge 104: Ausgebrannt (S07/E04)", others put
        the number first, or use a word the core has never heard of. Fill
        MediaItem.season and MediaItem.episode where you can determine them, and
        leave them at None where you cannot - the core then files the episode by
        its broadcast date, which works everywhere.
        """
        raise NotImplementedError
