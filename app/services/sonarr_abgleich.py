"""
Abgleich mit Sonarr fuer Sendungen, die Sonarr ebenfalls fuehrt.

Anlass (2026-10-07, "Hubert und Staller"): Sonarr und pbarr legen in DENSELBEN
Ordner. Sonarr bringt den Bestand, pbarr ergaenzt aus der Mediathek. Der Sender
nummeriert aber nicht immer wie TVDB - beim BR sind S02E14 und S02E15
vertauscht. Eine fehlende Folge unter der Sendernummer abzulegen hiesse: Plex
zeigt die falsche Folge, und Sonarr haelt eine vorhandene fuer fehlend.

Fuehrt Sonarr die Sendung, entscheidet deshalb der TITEL:

  Titel bei Sonarr gefunden, Datei vorhanden   -> nicht laden
  Titel gefunden, Datei fehlt                  -> laden, unter SONARRS Nummer
  Titel nicht gefunden, mit Sendernummer:
      Nummer bei Sonarr unbekannt oder "TBA"    -> Sendernummer (Sonarr kennt
                                                   die Folge noch nicht)
      Nummer gehoert dort einer ANDEREN Folge   -> nicht laden, Grund nennen
  weder Titeltreffer noch Nummer               -> keine Aussage, wie bisher

Welche Sonarr-Serie gemeint ist, ergibt der gemeinsame Ordner - kein eigenes
Feld, nichts zu pflegen. Nach einem Download bekommt Sonarr "RescanSeries",
damit es die Datei uebernimmt.

Ist Sonarr nicht eingerichtet, nicht erreichbar oder fuehrt die Sendung nicht,
liefert fuer_ordner() None - und pbarr verhaelt sich genau wie vorher.
"""
import difflib
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_NUMMER_IM_TITEL = re.compile(r"\s*\(\s*s\d+\s*/\s*e\d+\s*\)\s*", re.I)
_FOLGE_PRAEFIX = re.compile(r"^\s*(folge|episode|teil)\s*\d+\s*[:.\-–]\s*", re.I)
_FASSUNG = re.compile(r"\s*\((audiodeskription|gebärdensprache|mit gebärdensprache|"
                      r"klare sprache|originalversion|ov|mit untertiteln?)\)\s*", re.I)
# Titel, die nichts ueber die Folge aussagen
_PLATZHALTER = {"", "tba", "tbd", "folge", "episode", "unbekannt"}
# Ab hier gilt ein unscharfer Titeltreffer - nur wenn er eindeutig ist
_MINDEST, _ABSTAND = 0.88, 0.05


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(z for z in text if not unicodedata.combining(z))
    return re.sub(r"[^a-z0-9]+", "", text.replace("ß", "ss"))


def titelkern(titel: str, namen=()) -> str:
    """'Folge 104: Ausgebrannt (S07/E04) (Audiodeskription)' -> 'Ausgebrannt'."""
    t = titel or ""
    for name in namen:
        if name:
            t = re.sub(r"^\s*" + re.escape(name) + r"\s*[:\-–]\s*", "", t, flags=re.I)
    t = _NUMMER_IM_TITEL.sub(" ", t)
    t = _FASSUNG.sub(" ", t)
    t = _FOLGE_PRAEFIX.sub("", t)
    return t.strip()


@dataclass
class Entscheidung:
    laden: Optional[bool]          # True laden, False nicht, None keine Aussage
    staffel: Optional[int] = None
    folge: Optional[int] = None
    grund: str = ""


class SonarrAbgleich:
    def __init__(self, url: str, key: str, serie: dict, episoden: list):
        self.url, self.key = url.rstrip("/"), key
        self.serie = serie
        self.titel = serie.get("title", "")
        self.episoden = episoden
        self.nach_nummer = {(e["seasonNumber"], e["episodeNumber"]): e for e in episoden}

    # ----------------------------------------------------------------- laden

    @classmethod
    async def fuer_ordner(cls, db, ordnername: str) -> Optional["SonarrAbgleich"]:
        from app.models.config import Config
        from app.services.mediathek_direct import vergleichsname

        werte = {c.key: (c.value or "").strip() for c in
                 db.query(Config).filter(Config.key.in_(["sonarr_url", "sonarr_api_key"])).all()}
        url, key = werte.get("sonarr_url", ""), werte.get("sonarr_api_key", "")
        if not url or not key:
            return None
        try:
            async with httpx.AsyncClient(timeout=20, headers={"X-Api-Key": key}) as c:
                r = await c.get(f"{url.rstrip('/')}/api/v3/series")
                r.raise_for_status()
                ziel = vergleichsname(ordnername)
                treffer = [s for s in r.json()
                           if vergleichsname(PurePosixPath(s.get("path") or "").name) == ziel]
                if not treffer:
                    return None
                serie = treffer[0]
                r = await c.get(f"{url.rstrip('/')}/api/v3/episode",
                                params={"seriesId": serie["id"]})
                r.raise_for_status()
                return cls(url, key, serie, r.json())
        except (httpx.HTTPError, ValueError) as e:
            # Sonarr ist eine Hilfe, keine Voraussetzung.
            logger.warning(f"    Sonarr nicht befragbar ({e.__class__.__name__}) - Nummern wie bisher")
            return None

    async def rescan(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=20, headers={"X-Api-Key": self.key}) as c:
                await c.post(f"{self.url}/api/v3/command",
                             json={"name": "RescanSeries", "seriesId": self.serie["id"]})
            logger.info(f"    Sonarr: '{self.titel}' wird neu eingelesen")
        except httpx.HTTPError as e:
            logger.warning(f"    Sonarr-Rescan fehlgeschlagen: {e}")

    # ------------------------------------------------------------ entscheiden

    def _per_titel(self, kern: str) -> Optional[dict]:
        if len(kern) < 4:
            return None
        kandidaten = [e for e in self.episoden if _norm(e.get("title")) not in _PLATZHALTER]
        genau = [e for e in kandidaten if _norm(e.get("title")) == kern]
        if genau:
            return genau[0]
        bewertet = sorted(((difflib.SequenceMatcher(None, kern, _norm(e.get("title"))).ratio(), e)
                           for e in kandidaten), key=lambda x: -x[0])
        if bewertet and bewertet[0][0] >= _MINDEST and (
                len(bewertet) == 1 or bewertet[0][0] - bewertet[1][0] >= _ABSTAND):
            return bewertet[0][1]
        return None

    def zuordnen(self, item, namen=()) -> Entscheidung:
        kern = _norm(titelkern(item.title, namen))
        ep = self._per_titel(kern)
        if ep:
            nr = f"S{ep['seasonNumber']:02d}E{ep['episodeNumber']:02d}"
            if ep.get("hasFile"):
                return Entscheidung(False, grund=f"bei Sonarr vorhanden als {nr}")
            umnummeriert = (item.season, item.episode) != (ep["seasonNumber"], ep["episodeNumber"])
            return Entscheidung(True, ep["seasonNumber"], ep["episodeNumber"],
                                f"Sonarr-Nummer {nr}" + (" (Sender abweichend)" if
                                                       umnummeriert and item.season is not None else ""))
        if item.season is not None and item.episode is not None:
            nr = f"S{item.season:02d}E{item.episode:02d}"
            dort = self.nach_nummer.get((item.season, item.episode))
            if dort is None or _norm(dort.get("title")) in _PLATZHALTER:
                if dort is not None and dort.get("hasFile"):
                    return Entscheidung(False, grund=f"bei Sonarr vorhanden als {nr}")
                return Entscheidung(True, item.season, item.episode,
                                    f"Sendernummer {nr} (Sonarr kennt den Titel noch nicht)")
            return Entscheidung(False, grund=f"Sendernummer {nr} ist bei Sonarr "
                                              f"'{dort.get('title')}' - Titel passt nicht")
        return Entscheidung(None)
