"""
Suche fuer Sonarr und Radarr: pbarr als Indexer.

Sonarr fragt "Hast du Folge S03E05 der Serie mit TVDB 12345?", Radarr "Hast du den
Film tt0133093?". pbarr schlaegt bei Sonarr bzw. Radarr nach, wie die Serie oder
der Film heisst und wie die Folgen heissen, sucht in der Mediathek und ordnet die
Treffer ueber den TITEL zu - nicht ueber die Sendernummer, die oft von TVDB
abweicht (siehe sonarr_abgleich.py). Der Treffer bekommt einen Release-Namen in
der Form, die Sonarr und Radarr lesen koennen:

    Hubert.und.Staller.S02E14.Titel.GERMAN.1080p.WEB.h264-MEDiATHEK
    Der.Name.der.Rose.1986.GERMAN.1080p.WEB.h264-MEDiATHEK

Sonarr und Radarr entscheiden danach selbst - Sprache, Qualitaet, ob die Folge
schon da ist. pbarr liefert nur, was es sicher zuordnen kann; was es nicht
zuordnen kann, laesst es weg, statt zu raten.
"""
import asyncio
import difflib
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import httpx

from app.modules.sources.base import MediaItem, is_stream
from app.services.sonarr_abgleich import _norm, _PLATZHALTER, _MINDEST, _ABSTAND, titelkern

logger = logging.getLogger(__name__)

_BERLIN = ZoneInfo("Europe/Berlin")
_GRUPPE = "MEDiATHEK"
# Fassungen, die niemand als Folge oder Film haben will
_FASSUNGEN = ("audiodeskription", "hörfassung", "gebärdensprache", "klare sprache", "trailer")
# Woran die Sender die Aufloesung in der Adresse verraten (Stichprobe 2026-11-07):
# "1920x1080" (ARD, HR), "hd1080"/"avc1080"/"AVC-1080"/".1080." (RBB, MDR, WDR, NDR, SWR),
# "_p37" = 1080p und "_p36" = 720p (ZDF, 3sat, KiKA), "_HD.mp4" beim BR = 1080p (nachgemessen)
_HOEHE = re.compile(r"(?:\d{3,4}x(\d{3,4}))|(?:(?:hd|avc|avc-|[._-])(1080|720|540|480|360)(?:p\b|\b|[._-]))", re.I)
_ZDF = re.compile(r"_p(3[5-9])v\d+", re.I)


@dataclass
class Release:
    titel: str                  # Release-Name fuer Sonarr/Radarr
    video: str                  # Adresse der Datei
    groesse: int                # Bytes (geschaetzt, wenn der Sender keine nennt)
    datum: Optional[datetime]
    kategorie: int              # 5000 TV, 2000 Film
    beschreibung: str = ""
    attribute: dict = field(default_factory=dict)


# ---------------------------------------------------------------- Hilfen

def _punkte(text: str) -> str:
    """'Hubert und/ohne Staller: Folge 3' -> 'Hubert.und.ohne.Staller.Folge.3'"""
    text = (text or "").replace("&", "and").replace("ß", "ss")
    text = re.sub(r"[^\w]+", ".", text, flags=re.UNICODE)
    return text.strip(".")


def _aufloesung(url: str, qualitaet: str) -> str:
    url = url or ""
    m = _HOEHE.search(url)
    hoehe = int(m.group(1) or m.group(2)) if m else 0
    z = _ZDF.search(url)
    if not hoehe and z:
        hoehe = {"37": 1080, "36": 720, "35": 540}.get(z.group(1), 0)
    if not hoehe and ".br.de/" in url and url.endswith("_HD.mp4"):
        hoehe = 1080
    if hoehe >= 1000:
        return "1080p"
    if hoehe >= 700:
        return "720p"
    if hoehe:
        return "480p"
    return {"hd": "720p", "normal": "480p"}.get(qualitaet, "360p")


def _fassung(item: MediaItem) -> bool:
    text = f"{item.title} {item.topic}".lower()
    return any(w in text for w in _FASSUNGEN)


def _sendetag(item: MediaItem):
    return item.aired.astimezone(_BERLIN).date() if item.aired else None


async def _groessen(releases: list) -> None:
    """Fehlende Groessen per HEAD nachfragen (Sonarr prueft MB pro Minute)."""
    sperre = asyncio.Semaphore(8)

    async def eine(r):
        async with sperre:
            try:
                async with httpx.AsyncClient(timeout=6, follow_redirects=True) as c:
                    h = await c.head(r.video)
                    n = int(h.headers.get("content-length") or 0)
                    if n > 1_000_000:
                        r.groesse = n
            except (httpx.HTTPError, ValueError):
                pass

    await asyncio.gather(*(eine(r) for r in releases))


def _schaetzung(item: MediaItem, aufloesung: str) -> int:
    # Mittlere Datenraten der Mediatheken (MB pro Minute)
    mb = {"1080p": 40, "720p": 22, "480p": 11}.get(aufloesung, 6)
    return int((item.duration_seconds or 0) / 60 * mb * 1_000_000)


def _release(item: MediaItem, titel: str, kategorie: int, qualitaet: str, attribute: dict):
    url, gewaehlt = item.best_url(qualitaet)
    if not url or is_stream(url):
        return None
    aufl = _aufloesung(url, gewaehlt)
    name = f"{titel}.GERMAN.{aufl}.WEB.h264-{_GRUPPE}"
    return Release(name, url, _schaetzung(item, aufl), item.aired, kategorie,
                   f"{item.channel}: {item.topic} - {item.title}", attribute)


# ---------------------------------------------------------------- *arr-Zugang

class _Arr:
    """Zugang zu Sonarr oder Radarr aus pbarrs Einstellungen, mit kurzem Zwischenspeicher."""

    def __init__(self, art: str):
        self.art = art
        self._cache = {}

    def zugang(self, db):
        from app.models.config import Config
        schluessel = [f"{self.art}_url", f"{self.art}_api_key"]
        werte = {c.key: (c.value or "").strip() for c in
                 db.query(Config).filter(Config.key.in_(schluessel)).all()}
        url, key = werte.get(schluessel[0], ""), werte.get(schluessel[1], "")
        return (url.rstrip("/"), key) if url and key else (None, None)

    async def get(self, db, pfad: str, dauer: int = 600, **params):
        url, key = self.zugang(db)
        if not url:
            return None
        merk = (pfad, tuple(sorted(params.items())))
        hit = self._cache.get(merk)
        if hit and time.time() - hit[0] < dauer:
            return hit[1]
        try:
            async with httpx.AsyncClient(timeout=30, headers={"X-Api-Key": key}) as c:
                r = await c.get(f"{url}/api/v3/{pfad}", params=params)
                r.raise_for_status()
                daten = r.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.warning(f"{self.art} nicht befragbar ({pfad}): {e.__class__.__name__}")
            return None
        self._cache[merk] = (time.time(), daten)
        return daten


sonarr = _Arr("sonarr")
radarr = _Arr("radarr")


# ---------------------------------------------------------------- Zuordnung Folge

def folge_zuordnen(item: MediaItem, serie: dict, episoden: list, namen=()) -> Optional[dict]:
    """
    Welche Sonarr-Folge ist dieser Mediathek-Treffer? Sonst None.

    1. Titel (genau, sonst eindeutig aehnlich) - wie sonarr_abgleich
    2. Sendernummer, wenn Sonarr den Titel der Folge noch nicht kennt
    3. Sendetag, wenn an diesem Tag genau eine Folge lief (Tagesformate)
    """
    kern = _norm(titelkern(item.title, namen))
    kandidaten = [e for e in episoden if _norm(e.get("title")) not in _PLATZHALTER]
    if len(kern) >= 4:
        genau = [e for e in kandidaten if _norm(e.get("title")) == kern]
        if len(genau) == 1:
            return genau[0]
        bewertet = sorted(((difflib.SequenceMatcher(None, kern, _norm(e.get("title"))).ratio(), e)
                           for e in kandidaten), key=lambda x: -x[0])
        if bewertet and bewertet[0][0] >= _MINDEST and (
                len(bewertet) == 1 or bewertet[0][0] - bewertet[1][0] >= _ABSTAND):
            return bewertet[0][1]
    if item.season is not None and item.episode is not None:
        dort = next((e for e in episoden if (e["seasonNumber"], e["episodeNumber"]) ==
                     (item.season, item.episode)), None)
        if dort is not None and _norm(dort.get("title")) in _PLATZHALTER:
            return dort
    tag = _sendetag(item)
    if tag:
        am_tag = [e for e in episoden if e.get("airDate") == tag.isoformat() and e["seasonNumber"] > 0]
        if len(am_tag) == 1:
            return am_tag[0]
    return None


def _folgen_titel(serie: dict, ep: dict) -> str:
    name = _punkte(serie.get("title"))
    if _norm(ep.get("title")) in _PLATZHALTER:
        ep = {**ep, "title": ""}
    if serie.get("seriesType") == "daily" and ep.get("airDate"):
        return f"{name}.{ep['airDate'].replace('-', '.')}.{_punkte(ep.get('title'))}".rstrip(".")
    return f"{name}.S{ep['seasonNumber']:02d}E{ep['episodeNumber']:02d}.{_punkte(ep.get('title'))}".rstrip(".")


_SCHRAEG = re.compile(r"(\w+)\s*/\s*(\w+)")


def _varianten(name: str) -> list:
    """
    "Hubert und/ohne Staller" -> ["Hubert und/ohne Staller", "Hubert und Staller", "Hubert ohne Staller"]

    TVDB fasst Sendungen, die ihren Namen gewechselt haben, gern so zusammen; die
    Mediathek fuehrt jede Fassung unter ihrem eigenen Namen.
    """
    m = _SCHRAEG.search(name or "")
    if not m:
        return [name]
    return [name] + [name[:m.start()] + teil + name[m.end():] for teil in (m.group(1), m.group(2))]


def _namen(serie: dict, db) -> list:
    """Unter welchen Namen die Sendung in der Mediathek stehen kann."""
    namen = _varianten(serie.get("title") or "")
    for a in serie.get("alternateTitles") or []:
        namen += _varianten(a.get("title") or "")
    # Suchnamen aus pbarrs eigener Merkliste, wenn sie in denselben Ordner laedt
    try:
        from app.models.watch_list import WatchList
        from app.services.mediathek_direct import direct, vergleichsname
        ordner = vergleichsname((serie.get("path") or "").rstrip("/").split("/")[-1])
        for w in db.query(WatchList).all():
            if vergleichsname(direct.ordnername_fuer_eintrag(w)) == ordner:
                namen += [n.strip() for n in (w.search_topic or w.show_name or "").split("|")]
    except Exception as e:
        logger.debug(f"Merkliste nicht gelesen: {e}")
    gesehen, aus = set(), []
    for n in namen:
        if n and n.lower() not in gesehen:
            gesehen.add(n.lower())
            aus.append(n)
    return aus[:8]


async def _mediathek(db, namen: list) -> list:
    from app.services.mediathek_direct import direct
    treffer, gesehen = [], set()
    for n in namen:
        for item in await direct.search(n, db):
            if item.source_id not in gesehen:
                gesehen.add(item.source_id)
                treffer.append(item)
    return treffer


def _passt_dauer(item: MediaItem, laufzeit: int) -> bool:
    minuten = (item.duration_seconds or 0) / 60
    return minuten >= max(5, 0.6 * (laufzeit or 0))


# ---------------------------------------------------------------- Serien

async def serie_suchen(db, tvdbid: Optional[int], staffel: Optional[int], folge: Optional[int],
                       q: Optional[str], qualitaet: str = "hd") -> list:
    serien = await sonarr.get(db, "series") or []
    if tvdbid:
        serie = next((s for s in serien if s.get("tvdbId") == tvdbid), None)
    elif q:
        ziel = _norm(q)
        serie = next((s for s in serien if _norm(s.get("title")) == ziel), None)
    else:
        serie = None
    if not serie:
        return []
    episoden = await sonarr.get(db, "episode", dauer=120, seriesId=serie["id"]) or []
    gesucht = [e for e in episoden
               if (staffel is None or e["seasonNumber"] == staffel)
               and (folge is None or e["episodeNumber"] == folge)]
    if not gesucht:
        return []
    namen = _namen(serie, db)
    items = await _mediathek(db, namen)
    if not items and q is None:
        # Manche Sender legen Sendungen unter einer Sammelrubrik ab
        items = await _mediathek(db, [f"titel:{serie.get('title')}"])
    ids = {e["id"] for e in gesucht}
    releases, belegt = [], set()
    for item in items:
        if _fassung(item) or not _passt_dauer(item, serie.get("runtime")):
            continue
        ep = folge_zuordnen(item, serie, episoden, namen)
        if not ep or ep["id"] not in ids:
            continue
        r = _release(item, _folgen_titel(serie, ep), 5000, qualitaet,
                     {"tvdbid": serie.get("tvdbId"), "season": ep["seasonNumber"], "episode": ep["episodeNumber"]})
        # Dieselbe Folge laeuft oft auf mehreren Sendern - einmal reicht
        if r and (ep["id"], r.titel) not in belegt:
            belegt.add((ep["id"], r.titel))
            releases.append(r)
    await _groessen(releases)
    logger.info(f"Indexer: {serie.get('title')} S{staffel}E{folge} -> {len(releases)} Treffer")
    return releases


# ---------------------------------------------------------------- Filme

# "Schachnovelle - Spielfilm, Deutschland/Oesterreich 2020": Gattung, Land, Jahr
_GATTUNG = re.compile(r"\s[-–]\s(spielfilm|fernsehfilm|film|drama|komödie|tragikomödie|thriller|krimi|western|"
                      r"actionfilm|abenteuerfilm|liebesfilm|science-fiction|dokumentarfilm|animationsfilm)\b.*$", re.I)
_JAHR_KLAMMER = re.compile(r"\((19\d\d|20\d\d)\)")
_JAHR = re.compile(r"\b(19\d\d|20\d\d)\b")
_MEHRTEILER = re.compile(r"\(\s*\d+\s*/\s*\d+\s*\)")


def _film_passt(item: MediaItem, film: dict) -> bool:
    """
    Ist dieser Mediathek-Eintrag genau dieser Film?

    Streng, weil ein Fehlgriff einen falschen Film in die Bibliothek bringt:
    der ganze Titel muss passen (Gattungsangabe und Fassung abgezogen), eine
    genannte Jahreszahl hoechstens ein Jahr abweichen und die Laufzeit stimmen.
    Die Sender spielen mit 25 Bildern, Filme laufen dort gut 4 % kuerzer.
    Gemessen am 2026-11-07: ohne diese Regeln hielt pbarr "Cash (2024)" fuer
    "Walk the Line" (Alternativtitel "Cash") und "Dracula - Die wahre Geschichte"
    fuer einen anderen Dracula.
    """
    if _MEHRTEILER.search(item.title or ""):
        return False
    titel = {_norm(film.get("title")), _norm(film.get("originalTitle"))}
    titel |= {_norm(a.get("title")) for a in film.get("alternateTitles") or []}
    titel.discard("")
    gattung = _GATTUNG.search(item.title or "")
    rest = _GATTUNG.sub("", item.title or "")
    jahr = _JAHR_KLAMMER.search(rest) or (_JAHR.search(gattung.group(0)) if gattung else None)
    rest = _JAHR_KLAMMER.sub(" ", rest)
    if jahr and film.get("year") and abs(int(jahr.group(1)) - film["year"]) > 1:
        return False
    laufzeit = film.get("runtime") or 0
    minuten = (item.duration_seconds or 0) / 60
    if laufzeit and not (0.93 * laufzeit - 3 <= minuten <= 1.03 * laufzeit + 3):
        return False
    if _norm(titelkern(rest)) in titel:
        return True
    # "The Convert – Krieg der Maori - Spielfilm, ... 2024": Untertitel nur, wenn das Jahr es bestaetigt
    vorne = _norm(re.split(r"\s[-–:]\s", rest)[0])
    return bool(jahr) and vorne in titel


async def film_suchen(db, imdbid: Optional[str], tmdbid: Optional[int], q: Optional[str],
                      qualitaet: str = "hd") -> list:
    film = None
    filme = await radarr.get(db, "movie") or []
    if imdbid:
        imdbid = imdbid if imdbid.startswith("tt") else f"tt{imdbid}"
        film = next((f for f in filme if f.get("imdbId") == imdbid), None)
    if not film and tmdbid:
        film = next((f for f in filme if f.get("tmdbId") == tmdbid), None)
    if not film and q:
        ziel = _norm(re.sub(r"\b(19|20)\d\d\b", "", q))
        film = next((f for f in filme if _norm(f.get("title")) == ziel), None)
    if not film:
        return []
    namen = [film.get("title")] + ([film["originalTitle"]] if film.get("originalTitle") else [])
    items = await _mediathek(db, [f"titel:{n}" for n in dict.fromkeys(namen) if n])
    releases, belegt = [], set()
    for item in items:
        if _fassung(item) or (item.duration_seconds or 0) < 3600 or not _film_passt(item, film):
            continue
        r = _release(item, f"{_punkte(film.get('title'))}.{film.get('year')}", 2000, qualitaet,
                     {"imdb": (film.get("imdbId") or "").replace("tt", "")})
        if r and r.titel not in belegt:
            belegt.add(r.titel)
            releases.append(r)
    await _groessen(releases)
    logger.info(f"Indexer: Film {film.get('title')} ({film.get('year')}) -> {len(releases)} Treffer")
    return releases


# ---------------------------------------------------------------- RSS

_rss_cache = {}


async def neueste(db, kategorie: int, qualitaet: str = "hd") -> list:
    """
    Was die Mediathek in den letzten Tagen neu hat und zu Sonarr bzw. Radarr passt.

    Sonarr und Radarr fragen alle 15 Minuten ohne Suchbegriff (RSS). Nur so
    kommen neue Folgen von selbst - eine gezielte Suche gibt es nur beim
    Hinzufuegen oder auf Knopfdruck. Das Ergebnis wird 15 Minuten gehalten.
    """
    hit = _rss_cache.get(kategorie)
    if hit and time.time() - hit[0] < 900:
        return hit[1]
    from app.modules.sources.registry import enabled_sources
    items = []
    for quelle in enabled_sources(db):
        neu = getattr(quelle, "neueste", None)
        if neu:
            # Filme: nur Langes, dafuer reichen 2000 Eintraege etwa zwei Wochen zurueck
            items += await (neu() if kategorie == 5000 else neu(min_minuten=60))
    releases = []
    if kategorie == 5000:
        serien = {}
        for s in await sonarr.get(db, "series") or []:
            if s.get("monitored"):
                for t in [s.get("title")] + [a.get("title") for a in s.get("alternateTitles") or []]:
                    for v in _varianten(t or ""):
                        serien.setdefault(_norm(v), s)
        # Suchnamen aus pbarrs Merkliste ("Hubert ohne Staller" fuer "Hubert und/ohne Staller")
        try:
            from app.models.watch_list import WatchList
            from app.services.mediathek_direct import direct, vergleichsname
            nach_ordner = {vergleichsname((s.get("path") or "").rstrip("/").split("/")[-1]): s
                           for s in serien.values()}
            for w in db.query(WatchList).all():
                s = nach_ordner.get(vergleichsname(direct.ordnername_fuer_eintrag(w)))
                if s:
                    for n in (w.search_topic or w.show_name or "").split("|"):
                        if n.strip() and not n.strip().lower().startswith("titel:"):
                            serien.setdefault(_norm(n), s)
        except Exception as e:
            logger.debug(f"Merkliste nicht gelesen: {e}")
        nach_serie = {}
        for item in items:
            s = serien.get(_norm(item.topic))
            if s:
                nach_serie.setdefault(s["id"], (s, []))[1].append(item)
        for s, liste in nach_serie.values():
            episoden = await sonarr.get(db, "episode", dauer=600, seriesId=s["id"]) or []
            for item in liste:
                if _fassung(item) or not _passt_dauer(item, s.get("runtime")):
                    continue
                ep = folge_zuordnen(item, s, episoden)
                if ep and ep.get("monitored"):
                    r = _release(item, _folgen_titel(s, ep), 5000, qualitaet,
                                 {"tvdbid": s.get("tvdbId"), "season": ep["seasonNumber"],
                                  "episode": ep["episodeNumber"]})
                    if r:
                        releases.append(r)
    else:
        fehlend = [f for f in await radarr.get(db, "movie") or [] if f.get("monitored") and not f.get("hasFile")]
        for item in items:
            if _fassung(item):
                continue
            f = next((f for f in fehlend if _film_passt(item, f)), None)
            if f:
                r = _release(item, f"{_punkte(f.get('title'))}.{f.get('year')}", 2000, qualitaet,
                             {"imdb": (f.get("imdbId") or "").replace("tt", "")})
                if r:
                    releases.append(r)
    await _groessen(releases)
    _rss_cache[kategorie] = (time.time(), releases)
    logger.info(f"Indexer RSS ({'Serien' if kategorie == 5000 else 'Filme'}): "
                f"{len(items)} neue Mediathek-Eintraege, {len(releases)} passend")
    return releases
