"""
The part that is the same in every country.

Sources answer what a broadcaster currently offers (see modules/sources/base.py).
Everything from there on happens here and knows nothing about any particular
broadcaster: filtering, quality choice, file naming, downloading, remembering
what was fetched.

That split is the whole point. Someone who wants pbarr to reach their own
country's broadcaster writes one source module. They do not touch this file.

Why there is no episode matching left
-------------------------------------
The original design asked TVDB for an episode list, asked Sonarr what was
missing, and downloaded only where both agreed on a season/episode pair. They
never agreed - measured on a live instance, Sonarr wanted S00/S02/S04/S08 while
the cache held S01/S06/S07, with no overlap at all, and the episodes actually on
offer were not in Sonarr to begin with. Nothing was ever downloaded.

Numbering now comes from whoever produced the programme: the source when it
states it, otherwise the title, otherwise the broadcast date. Every media server
reads YYYY-MM-DD where a season/episode pair would go.
"""

import logging
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.modules.sources.base import MediaItem, is_stream

logger = logging.getLogger(__name__)

# characters that are unsafe or annoying in file names
_TRENNER = re.compile(r'[/\\]')
_UNSAFE = re.compile(r'[<>:"|?*\x00-\x1f]')
_SPACES = re.compile(r"\s+")

# A depublished link answers 403 or 404 for good. Without a limit it would be
# retried on every hourly run, forever.
MAX_ATTEMPTS = 3


def vergleichsname(text: str) -> str:
    """
    Einen Namen auf seinen Kern reduzieren, um Ordner vergleichen zu koennen.

    Gross-/Kleinschreibung, Akzente, Satzzeichen und Trennzeichen fallen weg.
    "Wer weiß denn sowas?" und "Wer weiss denn sowas" ergeben dasselbe.
    """
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(z for z in text if not unicodedata.combining(z))
    text = text.replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", "", text)


class MediathekDirect:
    def __init__(self, library_path: str = "/app/library"):
        self.library_path = Path(library_path)
        # Vorhandene Ordner der Bibliothek, einmal je Lauf eingelesen.
        self._ordner_verzeichnis = None

    # ------------------------------------------------------------------ search

    async def search(self, topic: str, db=None) -> list:
        """
        Ask every enabled source what it has under this name.

        Results are merged and deduplicated by source_id. An empty list means
        "nothing found or nothing reachable" - never "this show is gone".
        """
        from app.modules.sources.registry import enabled_sources

        items, seen = [], set()
        for source in enabled_sources(db):
            try:
                for item in await source.search(topic):
                    if item.source_id and item.source_id not in seen:
                        seen.add(item.source_id)
                        items.append(item)
            except Exception as e:
                # One broken source must not stop the others.
                logger.error(f"  Quelle '{source.name}' fehlgeschlagen: {e}")
        return items

    # ----------------------------------------------------------------- filters

    @staticmethod
    def passes_filters(item: MediaItem, min_minutes: int, max_minutes: int,
                       exclude_keywords: str, include_senders: str) -> tuple:
        """
        Check one item against a watchlist entry's filters.

        Returns (True, "") when it passes, (False, reason) otherwise. The reason
        is shown in the preview, so it is visible why something was skipped
        instead of having to guess.
        """
        duration_min = (item.duration_seconds or 0) / 60

        if min_minutes and duration_min < min_minutes:
            return False, f"zu kurz ({duration_min:.0f} < {min_minutes} min)"
        if max_minutes and duration_min > max_minutes:
            return False, f"zu lang ({duration_min:.0f} > {max_minutes} min)"

        haystack = f"{item.title} {item.description or ''}".lower()
        for word in (w.strip().lower() for w in (exclude_keywords or "").split(",")):
            if word and word in haystack:
                return False, f"Ausschlusswort '{word}'"

        senders = [s.strip().lower() for s in (include_senders or "").split(",") if s.strip()]
        if senders and (item.channel or "").lower() not in senders:
            return False, f"Sender '{item.channel}' nicht in Auswahl"

        return True, ""

    # ------------------------------------------------------------------ naming

    @staticmethod
    def extract_episode(item: MediaItem):
        """
        Determine season/episode, or (None, None).

        Reading a number out of a title is the source's job. Where a broadcaster
        writes it, and in which language, differs from country to country - the
        German patterns used to sit here and would have been meaningless to a
        Spanish or Danish connector. A source fills MediaItem.season and
        MediaItem.episode where it can; everything else is filed by date.
        """
        if item.season is not None and item.episode is not None:
            return item.season, item.episode
        return None, None

    @classmethod
    def sanitize(cls, text_value: str) -> str:
        """Strip characters that do not belong in a file name."""
        # Schraegstriche zuerst durch ein Leerzeichen ersetzen, nicht loeschen.
        # "Hubert und/ohne Staller" wurde sonst zu "Hubert undohne Staller" -
        # und genau so stuende der Ordner im Medienserver.
        # Bei einem Mehrfach-Thema zaehlt nur der erste Name.
        #
        # "Hubert und Staller|Hubert ohne Staller" ergab sonst den Ordner
        # "Hubert und StallerHubert ohne Staller" - eine Zeichenkette, die
        # kein Medienserver einer Serie zuordnen kann. Der erste Name ist der,
        # unter dem die Sendung gefuehrt wird.
        text_value = (text_value or "").split("|")[0]

        cleaned = _TRENNER.sub(" ", text_value)
        cleaned = _UNSAFE.sub("", cleaned)
        cleaned = _SPACES.sub(" ", cleaned).strip(" .")
        return cleaned[:150] or "Unbenannt"

    def bekannte_ordner(self) -> dict:
        """Die Ordner der Bibliothek, nach Vergleichsnamen abgelegt."""
        if self._ordner_verzeichnis is None:
            verzeichnis = {}
            try:
                for eintrag in self.library_path.iterdir():
                    if eintrag.is_dir():
                        verzeichnis.setdefault(vergleichsname(eintrag.name), eintrag.name)
            except OSError as e:
                logger.debug(f"Bibliothek nicht lesbar ({e}) - lege neu an")
            self._ordner_verzeichnis = verzeichnis
        return self._ordner_verzeichnis

    def ordner_fuer(self, show_name: str) -> str:
        """
        Der Ordnername fuer diese Sendung.

        Ein bereits vorhandener Ordner hat Vorrang vor einem neu gebildeten.
        Sonst entstuenden zwei Ordner fuer dieselbe Serie, sobald sich der Name
        in der Mediathek auch nur in einem Satzzeichen von dem unterscheidet,
        den ein anderes Programm einmal angelegt hat - der Medienserver zeigte
        dann zwei Serien.

        Verglichen wird ohne Gross-/Kleinschreibung, Akzente und Satzzeichen:
        "Wer weiss denn sowas" und "Wer weiß denn sowas?" sind derselbe Ordner.
        """
        eigener = self.sanitize(show_name)
        vorhanden = self.bekannte_ordner().get(vergleichsname(eigener))
        if vorhanden and vorhanden != eigener:
            logger.info(f"    Nutze vorhandenen Ordner '{vorhanden}' statt '{eigener}'")
        return vorhanden or eigener

    def build_path(self, show_name: str, item: MediaItem, url: str = None,
                   ordner: str = None, ablage: str = "flat") -> Path:
        """
        Where the file goes.

            <library>/<Show>/Season 07/<Show> - S07E04 - <Title>.<ext>
            <library>/<Show>/Season 2026/<Show> - 2026-08-20 - <Title>.<ext>

        Plex, Jellyfin and Emby all read both forms, so nothing here is tied to
        one media server.
        """
        # Vorrang: was der Nutzer bei der Sendung eingetragen hat, sonst ein
        # vorhandener Ordner der Bibliothek, sonst der Name selbst.
        show = self.sanitize(ordner) if (ordner or "").strip() else self.ordner_fuer(show_name)
        title = self.sanitize(item.title or "Ohne Titel")
        # Die Endung muss von der Adresse kommen, die tatsaechlich geladen
        # wird. Vorher stand hier fest "normal" - wer "hd" eingestellt hat und
        # eine Quelle nutzt, die je Qualitaet andere Formate liefert, bekam
        # eine Datei mit falscher Endung.
        if url is None:
            url, _ = item.best_url("normal")
        ext = Path((url or "").split("?")[0]).suffix or ".mp4"

        season, episode = self.extract_episode(item)
        aired = item.aired or datetime.now(timezone.utc)

        if season is not None:
            filename = f"{show} - S{season:02d}E{episode:02d} - {title}{ext}"
            unterordner = f"Season {season:02d}"
        else:
            filename = f"{show} - {aired:%Y-%m-%d} - {title}{ext}"
            unterordner = f"Season {aired:%Y}"

        # Flach ist die Vorgabe: bestehende Bibliotheken liegen meist so vor,
        # und beide Formen liest ohnehin jeder Medienserver.
        if (ablage or "flat").lower() == "seasons":
            return self.library_path / show / unterordner / filename
        return self.library_path / show / filename

    # ---------------------------------------------------------------- download

    async def download(self, url: str, target: Path) -> tuple:
        """
        Stream a file to disk. Returns (bytes_written, error) - error is None
        on success.

        Writes to a .part file and renames on success, so an aborted run never
        leaves something that looks complete to a media server.
        """
        # Abspiellisten sind keine Videos.
        #
        # Teile des Katalogs liegen nur als HLS vor. Wer so eine Adresse
        # herunterlaedt, bekommt 17 KB Text - und der Medienserver zeigt eine
        # Folge an, die sich nicht abspielen laesst. Lieber sichtbar scheitern:
        # der Fehlversuchszaehler haelt den Grund fest.
        if is_stream(url):
            return 0, "nur als HLS-Stream verfuegbar, keine Datei"

        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_suffix(target.suffix + ".part")
        written = 0
        try:
            async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
                async with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        logger.warning(f"    Download fehlgeschlagen: HTTP {resp.status_code}")
                        return 0, f"HTTP {resp.status_code}"
                    with open(part, "wb") as fh:
                        async for chunk in resp.aiter_bytes(chunk_size=1 << 20):
                            fh.write(chunk)
                            written += len(chunk)
            part.rename(target)
            return written, None
        except Exception as e:
            logger.warning(f"    Download abgebrochen: {e}")
            part.unlink(missing_ok=True)
            return 0, str(e)[:200]

    # -------------------------------------------------------------------- sync

    async def sync_entry(self, entry, db) -> int:
        """Bring one watchlist entry up to date. Returns how many were fetched."""
        raw = (getattr(entry, "search_topic", "") or entry.show_name or "").strip()
        if not raw:
            logger.warning(f"  Eintrag ohne Namen (key={entry.tvdb_id}) - uebersprungen")
            return 0

        # Several names separated by "|". Shows get renamed - "Hubert und
        # Staller" became "Hubert ohne Staller", both exist side by side, and
        # the combined name is in no index at all.
        topics = [t.strip() for t in raw.split("|") if t.strip()]

        items, seen = [], set()
        for topic in topics:
            for item in await self.search(topic, db):
                if item.source_id not in seen:
                    seen.add(item.source_id)
                    items.append(item)

        if not items:
            return 0
        if len(topics) > 1:
            logger.info(f"  {len(topics)} Namen zusammengefasst: {len(items)} Treffer")

        from app.models.mediathek_download import MediathekDownload

        # Erledigt ist, was geholt wurde - und was zu oft gescheitert ist.
        known, given_up = set(), set()
        for url, path, fails in db.query(
            MediathekDownload.source_url,
            MediathekDownload.file_path,
            MediathekDownload.failed_attempts,
        ).filter(MediathekDownload.watch_key == entry.tvdb_id).all():
            if path:
                known.add(url)
            elif (fails or 0) >= MAX_ATTEMPTS:
                given_up.add(url)

        wanted = getattr(entry, "quality", None) or "hd"
        fetched = skipped = 0

        for item in items:
            passes, reason = self.passes_filters(
                item, entry.min_duration or 0, entry.max_duration or 0,
                entry.exclude_keywords or "", entry.include_senders or "",
            )
            if not passes:
                logger.debug(f"    ⊘ {item.title[:50]} - {reason}")
                skipped += 1
                continue

            url, quality = item.best_url(wanted)
            if not url or url in known or url in given_up:
                continue

            target = self.build_path(
                entry.show_name, item, url,
                ordner=getattr(entry, "library_folder", "") or "",
                ablage=getattr(entry, "season_layout", "flat") or "flat",
            )
            if target.exists():
                # Already there from an earlier run or copied in by hand.
                self._record(db, entry, item, url, quality, target, target.stat().st_size)
                known.add(url)
                continue

            logger.info(f"    ↓ {item.title[:60]} [{quality}]")
            size, error = await self.download(url, target)
            if size:
                self._record(db, entry, item, url, quality, target, size)
                known.add(url)
                fetched += 1
                logger.info(f"      ✓ {size / 1048576:.0f} MB → {target.name}")
            else:
                attempts = self._record_failure(db, entry, item, url, quality, error)
                if attempts >= MAX_ATTEMPTS:
                    given_up.add(url)
                    logger.warning(
                        f"      ✗ nach {attempts} Versuchen aufgegeben: {item.title[:44]} ({error})"
                    )
                else:
                    logger.warning(
                        f"      ✗ Versuch {attempts}/{MAX_ATTEMPTS}: {item.title[:44]} ({error})"
                    )

        if fetched or skipped:
            logger.info(f"  '{topics[0]}': {fetched} geholt, {skipped} gefiltert, {len(known)} bekannt")
        return fetched

    @staticmethod
    def _record(db, entry, item: MediaItem, url, quality, target, size):
        """Write one download into the ledger. Duplicates are ignored."""
        from app.models.mediathek_download import MediathekDownload

        season, episode = MediathekDirect.extract_episode(item)
        aired = item.aired.replace(tzinfo=None) if item.aired else None
        try:
            db.add(MediathekDownload(
                watch_key=entry.tvdb_id,
                show_name=entry.show_name,
                source_url=url,
                channel=item.channel,
                topic=item.topic,
                title=item.title,
                aired=aired,
                duration_seconds=item.duration_seconds,
                quality=quality,
                season=season,
                episode=episode,
                file_path=str(target),
                file_size=size,
            ))
            db.commit()
        except Exception as e:
            db.rollback()
            logger.debug(f"      (nicht vermerkt: {e})")

    @staticmethod
    def _record_failure(db, entry, item: MediaItem, url, quality, error) -> int:
        """
        Note a failed attempt and return how many there have been.

        Failures share the ledger with successes, distinguished by file_path
        being empty. That keeps one place to look when asking "what happened to
        this programme".
        """
        from app.models.mediathek_download import MediathekDownload

        try:
            row = db.query(MediathekDownload).filter(
                MediathekDownload.watch_key == entry.tvdb_id,
                MediathekDownload.source_url == url,
            ).first()

            if row is None:
                season, episode = MediathekDirect.extract_episode(item)
                row = MediathekDownload(
                    watch_key=entry.tvdb_id,
                    show_name=entry.show_name,
                    source_url=url,
                    channel=item.channel,
                    topic=item.topic,
                    title=item.title,
                    aired=item.aired.replace(tzinfo=None) if item.aired else None,
                    duration_seconds=item.duration_seconds,
                    quality=quality,
                    season=season,
                    episode=episode,
                    file_path=None,
                    failed_attempts=0,
                )
                db.add(row)

            row.failed_attempts = (row.failed_attempts or 0) + 1
            row.last_error = (error or "")[:200]
            row.last_attempt = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
            return row.failed_attempts
        except Exception as e:
            db.rollback()
            logger.debug(f"      (Fehlversuch nicht vermerkt: {e})")
            return 0

    async def sync_watchlist(self):
        """Hourly entry point. Opens its own session - the scheduler passes none."""
        from app.database import SessionLocal
        from app.models.watch_list import WatchList

        # Ordnerliste je Lauf neu einlesen - zwischen zwei Laeufen kann jemand
        # umbenannt oder aufgeraeumt haben.
        self._ordner_verzeichnis = None

        db = SessionLocal()
        try:
            entries = db.query(WatchList).all()
            if not entries:
                logger.info("🔄 Abgleich: Watch-List ist leer")
                return

            logger.info(f"🔄 Abgleich fuer {len(entries)} Eintrag/Eintraege...")
            total = 0
            for entry in entries:
                try:
                    total += await self.sync_entry(entry, db)
                except Exception as e:
                    logger.error(f"  Fehler bei '{entry.show_name}': {e}", exc_info=True)
            logger.info(f"✅ Abgleich fertig: {total} neue Sendung(en)")
        finally:
            db.close()


direct = MediathekDirect()
