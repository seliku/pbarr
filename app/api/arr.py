"""
Schnittstellen fuer Sonarr und Radarr.

  /newznab/api    pbarr als Indexer (Newznab). In Sonarr/Radarr:
                  Indexer "Newznab", URL http://<pbarr>:8070/newznab, API-Pfad /api
  /sabnzbd/api    pbarr als Download-Client (SABnzbd). In Sonarr/Radarr:
                  Download-Client "SABnzbd", Host <pbarr>, Port 8070, URL-Basis /sabnzbd

Beide nehmen den Schluessel aus der Einstellung "arr_api_key".

Die NZB, die der Indexer ausliefert, ist nur ein Umschlag: sie traegt die
Mediathek-Adresse und den Release-Namen als Kommentar und eine Attrappe als
Inhalt, weil Sonarr leere NZB ablehnt. Lesen kann sie nur pbarrs eigener
Download-Client - an einen echten SABnzbd geschickt, scheitert sie sofort und
sichtbar, statt etwas Falsches zu laden.
"""
import base64
import json
import logging
import re
import time
from datetime import datetime, timezone
from email.utils import format_datetime
from hashlib import sha1
from typing import Optional
from xml.sax.saxutils import escape, quoteattr

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.config import Config
from app.services import arr_suche
from app.services.arr_laden import warteschlange

logger = logging.getLogger(__name__)

router = APIRouter(tags=["arr"])

_UMSCHLAG = re.compile(r"pbarr:([A-Za-z0-9_\-]+=*)")


def _schluessel_ok(db: Session, apikey: Optional[str]) -> bool:
    c = db.query(Config).filter_by(key="arr_api_key").first()
    soll = (c.value or "").strip() if c else ""
    return not soll or apikey == soll


def _qualitaet(db: Session) -> str:
    c = db.query(Config).filter_by(key="arr_quality").first()
    return (c.value or "hd").strip() if c and c.value else "hd"


def _verpacken(daten: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(daten, ensure_ascii=False).encode()).decode()


def _auspacken(text: str) -> Optional[dict]:
    try:
        return json.loads(base64.urlsafe_b64decode(text.encode()))
    except Exception:
        return None


# ===================================================================== Newznab

_CAPS = """<?xml version="1.0" encoding="UTF-8"?>
<caps>
  <server title="pbarr"/>
  <limits max="100" default="100"/>
  <registration available="no" open="no"/>
  <searching>
    <search available="yes" supportedParams="q"/>
    <tv-search available="yes" supportedParams="q,season,ep,tvdbid"/>
    <movie-search available="yes" supportedParams="q,imdbid,tmdbid"/>
    <audio-search available="no" supportedParams=""/>
  </searching>
  <categories>
    <category id="2000" name="Movies"><subcat id="2040" name="HD"/><subcat id="2030" name="SD"/></category>
    <category id="5000" name="TV"><subcat id="5040" name="HD"/><subcat id="5030" name="SD"/></category>
  </categories>
</caps>"""


def _rss(releases: list, basis: str, apikey: str) -> str:
    teile = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
             'xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/">',
             "<channel><title>pbarr</title><description>Mediatheken</description>",
             f'<newznab:response offset="0" total="{len(releases)}"/>']
    for r in releases:
        umschlag = _verpacken({"v": r.video, "n": r.titel})
        link = f"{basis}/newznab/nzb/{umschlag}" + (f"?apikey={apikey}" if apikey else "")
        guid = sha1(f"{r.video}|{r.titel}".encode()).hexdigest()
        unterkat = (r.kategorie + 40) if ("1080p" in r.titel or "720p" in r.titel) else (r.kategorie + 30)
        datum = format_datetime(r.datum or datetime.now(timezone.utc))
        teile.append("<item>")
        teile.append(f"<title>{escape(r.titel)}</title>")
        teile.append(f'<guid isPermaLink="false">{guid}</guid>')
        teile.append(f"<link>{escape(link)}</link>")
        teile.append(f"<comments>{escape(r.video)}</comments>")
        teile.append(f"<pubDate>{datum}</pubDate>")
        teile.append(f"<description>{escape(r.beschreibung)}</description>")
        teile.append(f'<enclosure url={quoteattr(link)} length="{r.groesse}" type="application/x-nzb"/>')
        for k in (r.kategorie, unterkat):
            teile.append(f'<newznab:attr name="category" value="{k}"/>')
        teile.append(f'<newznab:attr name="size" value="{r.groesse}"/>')
        for k, v in r.attribute.items():
            teile.append(f'<newznab:attr name={quoteattr(k)} value={quoteattr(str(v))}/>')
        teile.append("</item>")
    teile.append("</channel></rss>")
    return "\n".join(teile)


def _zahl(text) -> Optional[int]:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return None


@router.get("/newznab/api")
async def newznab(request: Request, db: Session = Depends(get_db)):
    p = request.query_params
    if not _schluessel_ok(db, p.get("apikey")):
        return Response('<error code="100" description="Incorrect user credentials"/>',
                        media_type="application/xml", status_code=401)
    t = (p.get("t") or "").lower()
    if t == "caps":
        return Response(_CAPS, media_type="application/xml")
    if t not in ("search", "tvsearch", "movie"):
        return Response('<error code="202" description="No such function"/>', media_type="application/xml")

    # Sonarr blaettert, solange volle Seiten kommen - alles steht auf der ersten
    if (_zahl(p.get("offset")) or 0) > 0:
        return Response(_rss([], "", ""), media_type="application/xml")

    kats = {(_zahl(k) or 0) // 1000 * 1000 for k in (p.get("cat") or "").split(",") if k}
    q = (p.get("q") or "").strip() or None
    tvdbid, imdbid, tmdbid = _zahl(p.get("tvdbid")), p.get("imdbid"), _zahl(p.get("tmdbid"))
    staffel, folge = _zahl(p.get("season")), _zahl(p.get("ep"))
    qualitaet = _qualitaet(db)
    releases = []
    try:
        if t == "tvsearch" or (t == "search" and (not kats or 5000 in kats)):
            if tvdbid or q:
                releases += await arr_suche.serie_suchen(db, tvdbid, staffel, folge, q, qualitaet)
            else:
                releases += await arr_suche.neueste(db, 5000, qualitaet)
        if t == "movie" or (t == "search" and (not kats or 2000 in kats)):
            if imdbid or tmdbid or q:
                releases += await arr_suche.film_suchen(db, imdbid, tmdbid, q, qualitaet)
            else:
                releases += await arr_suche.neueste(db, 2000, qualitaet)
    except Exception as e:
        logger.exception(f"Indexer-Suche fehlgeschlagen: {e}")
    rss = not (q or tvdbid or imdbid or tmdbid)
    if rss and not releases:
        # Sonarr und Radarr lehnen beim Einrichten einen Indexer ab, dessen RSS leer
        # ist. Der Platzhalter traegt keine Folgen- oder Jahresangabe und passt so
        # zu keiner Serie und keinem Film - geladen wird er nie.
        releases = [arr_suche.Release("pbarr-Verbindungstest-keine-neuen-Sendungen", "http://pbarr.invalid/",
                                      1_000_000, None, 2000 if t == "movie" else 5000, "Platzhalter")]
    basis = str(request.base_url).rstrip("/")
    return Response(_rss(releases, basis, p.get("apikey") or ""), media_type="application/xml")


@router.get("/newznab/nzb/{umschlag}")
async def nzb(umschlag: str, apikey: Optional[str] = None, db: Session = Depends(get_db)):
    if not _schluessel_ok(db, apikey):
        return Response("forbidden", status_code=401)
    daten = _auspacken(umschlag)
    if not daten or not daten.get("v"):
        return Response("unbekannt", status_code=404)
    name = daten.get("n") or "mediathek"
    inhalt = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE nzb PUBLIC "-//newzBin//DTD NZB 1.0//EN" "http://www.newzbin.com/DTD/nzb/nzb-1.0.dtd">
<!-- pbarr:{umschlag} -->
<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">
  <head><meta type="name">{escape(name)}</meta></head>
  <file poster="pbarr" date="{int(time.time())}" subject={quoteattr(name + '.mp4')}>
    <groups><group>alt.binaries.pbarr</group></groups>
    <segments><segment bytes="1" number="1">nur-fuer-pbarr@pbarr</segment></segments>
  </file>
</nzb>"""
    return Response(inhalt, media_type="application/x-nzb",
                    headers={"Content-Disposition": f'attachment; filename="{name}.nzb"'})


# ===================================================================== SABnzbd

def _mb(n: int) -> str:
    return f"{n / 1048576:.2f}"


def _restzeit(a) -> str:
    if not a.gesamt or not a.geschrieben:
        return "0:10:00"
    dauer = max(1.0, time.time() - a.erstellt)
    rest = int((a.gesamt - a.geschrieben) / max(1.0, a.geschrieben / dauer))
    return f"{rest // 3600}:{rest % 3600 // 60:02d}:{rest % 60:02d}"


def _config() -> dict:
    kategorien = ["*", "tv", "sonarr", "movie", "movies", "radarr", "default"]
    return {"config": {
        "misc": {"complete_dir": str(warteschlange.wurzel()), "download_dir": str(warteschlange.wurzel()),
                 "enable_tv_sorting": 0, "enable_movie_sorting": 0, "enable_date_sorting": 0,
                 "pre_check": 0, "history_retention": "", "history_retention_option": "all",
                 "history_retention_number": 0},
        "categories": [{"name": k, "pp": "", "script": "Default", "dir": k if k != "*" else "",
                        "priority": -100} for k in kategorien],
        "sorters": [],
    }}


@router.api_route("/sabnzbd/api", methods=["GET", "POST"])
async def sabnzbd(request: Request, db: Session = Depends(get_db)):
    p = request.query_params
    if not _schluessel_ok(db, p.get("apikey")):
        return JSONResponse({"status": False, "error": "API Key Incorrect"})
    mode = p.get("mode") or ""
    name, wert = p.get("name"), p.get("value")

    if mode == "version":
        return {"version": "4.3.3"}
    if mode == "get_config":
        return _config()
    if mode == "fullstatus":
        return {"status": {"completedir": str(warteschlange.wurzel()), "paused": False}}

    if mode in ("addfile", "addurl"):
        if mode == "addfile":
            text = (await request.body()).decode("utf-8", "replace")
        else:
            text = name or ""
            m = re.search(r"/newznab/nzb/([A-Za-z0-9_\-]+=*)", text)
            text = f"pbarr:{m.group(1)}" if m else ""
        m = _UMSCHLAG.search(text)
        daten = _auspacken(m.group(1)) if m else None
        if not daten or not daten.get("v"):
            return {"status": False, "error": "keine pbarr-NZB"}
        nzo = warteschlange.hinzufuegen(daten.get("n") or "mediathek", daten["v"], p.get("cat") or "default")
        return {"status": True, "nzo_ids": [nzo]}

    if mode == "queue":
        if name == "delete" and wert:
            ok = all(warteschlange.entfernen(i, True) for i in wert.split(","))
            return {"status": ok, "nzo_ids": wert.split(",")}
        if name in ("pause", "resume"):
            return {"status": True}
        slots = []
        for i, a in enumerate(warteschlange.warteschlange()):
            prozent = int(a.geschrieben * 100 / a.gesamt) if a.gesamt else 0
            slots.append({"status": a.status, "index": i, "timeleft": _restzeit(a),
                          "mb": _mb(a.gesamt), "mbleft": _mb(max(0, a.gesamt - a.geschrieben)),
                          "filename": a.name, "priority": "Normal", "cat": a.kategorie,
                          "percentage": str(prozent), "nzo_id": a.id})
        return {"queue": {"paused": False, "slots": slots, "noofslots": len(slots)}}

    if mode == "history":
        if name == "delete" and wert:
            ok = all(warteschlange.entfernen(i, p.get("del_files") == "1") for i in wert.split(","))
            return {"status": ok}
        kat = p.get("category")
        slots = [{"nzo_id": a.id, "name": a.name, "nzb_name": f"{a.name}.nzb", "category": a.kategorie,
                  "bytes": a.gesamt, "status": a.status, "storage": a.ordner,
                  "fail_message": a.fehler, "download_time": int((a.beendet or time.time()) - a.erstellt)}
                 for a in warteschlange.verlauf() if not kat or kat in ("*", a.kategorie)]
        return {"history": {"slots": slots, "noofslots": len(slots)}}

    if mode in ("pause", "resume", "retry", "change_cat", "switch", "priority"):
        return {"status": True}
    return JSONResponse({"status": False, "error": "not implemented"}, status_code=400)
