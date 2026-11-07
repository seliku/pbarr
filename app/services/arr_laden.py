"""
Download-Warteschlange fuer Sonarr und Radarr: pbarr als SABnzbd.

Sonarr und Radarr schicken den gewaehlten Treffer als NZB an ihren
Download-Client. pbarr gibt sich als SABnzbd aus, nimmt die NZB an, liest die
Mediathek-Adresse heraus (die NZB ist nur ein Umschlag, siehe api/arr.py) und
laedt die Datei nach

    <arr_download_dir>/<Kategorie>/<Release-Name>/<Release-Name>.mp4

Sonarr und Radarr sehen in der Warteschlange den Fortschritt und im Verlauf den
fertigen Ordner, importieren von dort und raeumen danach den Verlaufseintrag
samt Ordner ab - genau wie bei SABnzbd.

Der Pfad muss fuer Sonarr/Radarr derselbe sein wie fuer pbarr (gleiche
Einbindung im Container), sonst braucht es dort eine "Remote Path Mapping".

Der Stand liegt in /app/data/arr-downloads.json und uebersteht Neustarts:
was gerade lief, beginnt von vorn.
"""
import asyncio
import json
import logging
import shutil
import time
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

from app.database import SessionLocal

logger = logging.getLogger(__name__)

STANDARD_ORDNER = "/app/downloads/arr"


@dataclass
class Auftrag:
    id: str
    name: str
    kategorie: str
    video: str
    status: str = "Queued"            # Queued, Downloading, Completed, Failed
    geschrieben: int = 0
    gesamt: int = 0
    erstellt: float = field(default_factory=time.time)
    beendet: float = 0
    ordner: str = ""
    fehler: str = ""
    versuche: int = 0


class Warteschlange:
    def __init__(self, datei: str = "/app/data/arr-downloads.json"):
        self.datei = Path(datei)
        self.auftraege: dict = {}
        self._laufend: set = set()
        self._geladen = False

    # ------------------------------------------------------------- Zustand

    def _laden(self):
        if self._geladen:
            return
        self._geladen = True
        try:
            for a in json.loads(self.datei.read_text()):
                a = Auftrag(**a)
                if a.status == "Downloading":
                    a.status, a.geschrieben = "Queued", 0
                self.auftraege[a.id] = a
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error(f"arr-Warteschlange nicht lesbar, beginne leer: {e}")

    def _speichern(self):
        # Verlauf begrenzen: was Sonarr/Radarr nach 14 Tagen nicht abgeholt hat, vergessen
        grenze = time.time() - 14 * 86400
        for a in [a for a in self.auftraege.values() if a.beendet and a.beendet < grenze]:
            del self.auftraege[a.id]
        try:
            self.datei.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.datei.with_suffix(".tmp")
            tmp.write_text(json.dumps([asdict(a) for a in self.auftraege.values()], ensure_ascii=False))
            tmp.replace(self.datei)
        except Exception as e:
            logger.error(f"arr-Warteschlange nicht gespeichert: {e}")

    @staticmethod
    def _einstellung(schluessel: str, vorgabe: str) -> str:
        from app.models.config import Config
        db = SessionLocal()
        try:
            c = db.query(Config).filter_by(key=schluessel).first()
            return (c.value or "").strip() if c and c.value else vorgabe
        finally:
            db.close()

    def wurzel(self) -> Path:
        return Path(self._einstellung("arr_download_dir", STANDARD_ORDNER))

    # ------------------------------------------------------------- SABnzbd-Sicht

    def hinzufuegen(self, name: str, video: str, kategorie: str) -> str:
        self._laden()
        # Dasselbe Release zweimal (Sonarr wiederholt bei Zeitueberschreitung): eines reicht
        for a in self.auftraege.values():
            if a.name == name and a.status in ("Queued", "Downloading"):
                return a.id
        a = Auftrag(id=f"SABnzbd_nzo_{uuid.uuid4().hex[:12]}", name=name,
                    kategorie=kategorie or "default", video=video)
        self.auftraege[a.id] = a
        self._speichern()
        logger.info(f"arr: aufgenommen [{a.kategorie}] {name}")
        return a.id

    def warteschlange(self) -> list:
        self._laden()
        return [a for a in sorted(self.auftraege.values(), key=lambda a: a.erstellt)
                if a.status in ("Queued", "Downloading")]

    def verlauf(self) -> list:
        self._laden()
        return [a for a in sorted(self.auftraege.values(), key=lambda a: -a.erstellt)
                if a.status in ("Completed", "Failed")]

    def entfernen(self, nzo_id: str, dateien: bool) -> bool:
        self._laden()
        a = self.auftraege.pop(nzo_id, None)
        if not a:
            return False
        # Laeuft er noch, bricht der Arbeiter ab, sobald er merkt, dass der Auftrag fehlt
        if dateien or a.status != "Completed":
            ordner = Path(a.ordner) if a.ordner else self.wurzel() / a.kategorie / a.name
            if ordner.is_dir() and ordner.parent.parent == self.wurzel():
                shutil.rmtree(ordner, ignore_errors=True)
        self._speichern()
        logger.info(f"arr: entfernt {a.name}" + (" samt Dateien" if dateien else ""))
        return True

    # ------------------------------------------------------------- Arbeiter

    async def arbeiter(self):
        """Laeuft fuer immer: nimmt wartende Auftraege und laedt sie."""
        self._laden()
        while True:
            try:
                parallel = int(self._einstellung("max_concurrent_downloads", "2") or 2)
                for a in self.warteschlange():
                    if len(self._laufend) >= parallel:
                        break
                    if a.status == "Queued" and a.id not in self._laufend:
                        self._laufend.add(a.id)
                        asyncio.create_task(self._laden_auftrag(a))
            except Exception as e:
                logger.error(f"arr-Arbeiter: {e}")
            await asyncio.sleep(3)

    async def _laden_auftrag(self, a: Auftrag):
        from app.services.mediathek_direct import direct
        try:
            versuche = int(self._einstellung("download_retry_count", "3") or 3)
            endung = Path(a.video.split("?")[0]).suffix.lower()
            if endung not in (".mp4", ".mkv", ".webm", ".mov"):
                endung = ".mp4"
            ordner = self.wurzel() / a.kategorie / a.name
            ziel = ordner / f"{a.name}{endung}"
            a.status, a.ordner, a.fehler = "Downloading", str(ordner), ""
            self._speichern()

            def fortschritt(geschrieben, gesamt):
                if a.id not in self.auftraege:
                    # Von Sonarr/Radarr entfernt: nicht weiter laden (der Downloader
                    # verwirft die angefangene Datei)
                    raise RuntimeError("entfernt")
                a.geschrieben, a.gesamt = geschrieben, gesamt or a.gesamt

            while True:
                a.versuche += 1
                geschrieben, fehler = await direct.download(a.video, ziel, fortschritt)
                if a.id not in self.auftraege:
                    # Waehrenddessen von Sonarr/Radarr entfernt
                    shutil.rmtree(ordner, ignore_errors=True)
                    return
                if not fehler:
                    a.status, a.geschrieben, a.gesamt = "Completed", geschrieben, geschrieben
                    logger.info(f"arr: fertig {a.name} ({geschrieben / 1048576:.0f} MB)")
                    break
                if a.versuche >= versuche or "HLS" in fehler:
                    a.status, a.fehler = "Failed", fehler
                    logger.warning(f"arr: fehlgeschlagen {a.name}: {fehler}")
                    break
                await asyncio.sleep(30 * a.versuche)
            a.beendet = time.time()
            self._speichern()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            a.status, a.fehler, a.beendet = "Failed", str(e)[:200], time.time()
            self._speichern()
            logger.error(f"arr: Fehler bei {a.name}: {e}")
        finally:
            self._laufend.discard(a.id)


warteschlange = Warteschlange()
