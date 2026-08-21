from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import os
import logging
import httpx


from app.database import get_db
from app.models.config import Config
from app.models.module_state import ModuleState
from app.models.watch_list import WatchList
from app.modules.sources.base import is_stream
from app.modules.sources.registry import enabled_sources


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/admin", tags=["admin"])


# Pydantic Schemas
class ConfigCreate(BaseModel):
    key: str
    value: str
    module: str = "core"
    secret: bool = False
    data_type: str = "string"
    description: Optional[str] = None


class ConfigUpdate(BaseModel):
    value: str


class ConfigResponse(BaseModel):
    id: int
    key: str
    value: str
    module: str
    secret: bool
    data_type: str
    description: Optional[str]
    updated_at: datetime

    class Config:
        from_attributes = True


class ModuleResponse(BaseModel):
    id: int
    module_name: str
    module_type: str
    enabled: bool
    version: str
    last_updated: datetime

    # Was die Quelle selbst ueber sich sagt. Leer, wenn zu der Zeile in der
    # Datenbank kein geladenes Modul gehoert.
    country: str = ""
    description: str = ""
    default_exclude: str = ""

    class Config:
        from_attributes = True


class AddByTopicRequest(BaseModel):
    """
    Add a show by the name the Mediathek uses for it.

    No TVDB id, no Sonarr entry, nothing to look up first - the topic string is
    the whole identity. Shows that Sonarr refuses to carry work through this
    path, which is the entire point of it.
    """
    topic: str
    display_name: Optional[str] = None
    quality: str = "hd"
    min_duration: int = 0
    max_duration: int = 360
    exclude_keywords: Optional[str] = None   # None = Vorgabe der aktiven Quellen
    library_folder: Optional[str] = None     # leer = vorhandener Ordner bzw. Name
    season_layout: str = "flat"              # flat | seasons
    include_senders: str = ""


class SeriesFiltersRequest(BaseModel):
    min_duration: Optional[int] = None
    quality: Optional[str] = None
    search_topic: Optional[str] = None
    max_duration: Optional[int] = None
    exclude_keywords: Optional[str] = None
    include_senders: Optional[str] = None
    search_title_filter: Optional[bool] = None
    custom_search_title: Optional[str] = None
    library_folder: Optional[str] = None
    season_layout: Optional[str] = None





# HTML Admin Panel
@router.get("/")
async def admin_panel():
    """
    Weiterleitung auf die Wurzel.

    Die Oberflaeche lag frueher hier. Bestehende Lesezeichen sollen weiter
    funktionieren, deshalb bleibt der Pfad - aber nur als Wegweiser. Die
    Schnittstellen unter /admin/... sind davon unberuehrt.
    """
    return RedirectResponse(url="/", status_code=308)


# Endpoints
@router.get("/config", response_model=List[ConfigResponse])
async def get_all_config(db: Session = Depends(get_db)):
    """Alle Konfigurationen abrufen"""
    configs = db.query(Config).order_by(Config.module, Config.key).all()
    return configs


@router.get("/config/{key}", response_model=ConfigResponse)
async def get_config(key: str, db: Session = Depends(get_db)):
    """Einzelne Konfiguration abrufen"""
    config = db.query(Config).filter(Config.key == key).first()
    if not config:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")
    return config


@router.post("/config", response_model=ConfigResponse)
async def create_config(config: ConfigCreate, db: Session = Depends(get_db)):
    """Neue Konfiguration erstellen"""
    existing = db.query(Config).filter(Config.key == config.key).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Config key '{config.key}' already exists")
    
    new_config = Config(**config.dict())
    db.add(new_config)
    db.commit()
    db.refresh(new_config)
    return new_config


@router.put("/config/{key}", response_model=ConfigResponse)
async def update_config(key: str, update: ConfigUpdate, db: Session = Depends(get_db)):
    """Konfiguration aktualisieren (Value only)"""
    config = db.query(Config).filter_by(key=key).first()
    if not config:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")

    config.value = update.value
    config.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(config)

    # WICHTIG: Wenn Log-Level geändert, sofort anwenden!
    if key == "log_level":
        from app.utils.logger import change_log_level_runtime
        if change_log_level_runtime(update.value):
            logger.info(f"Log-Level updated to {update.value}")
        else:
            logger.warning(f"Failed to update log level to {update.value}")

    return config


@router.delete("/config/{key}")
async def delete_config(key: str, db: Session = Depends(get_db)):
    """Konfiguration löschen"""
    config = db.query(Config).filter(Config.key == key).first()
    if not config:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")
    
    db.delete(config)
    db.commit()
    return {"message": f"Config key '{key}' deleted"}


# Module Management
@router.get("/modules", response_model=List[ModuleResponse])
async def get_modules(db: Session = Depends(get_db)):
    """Alle Module abrufen"""
    # Die angemeldeten Eigenheiten der Quelle mitliefern, damit die Oberflaeche
    # ihre Vorgaben nicht selbst kennen muss.
    gefunden = {q.name: q for q in enabled_sources(db)}
    ergebnis = []
    for zeile in db.query(ModuleState).all():
        quelle = gefunden.get(zeile.module_name)
        ergebnis.append({
            "id": zeile.id,
            "last_updated": zeile.last_updated,
            "module_name": zeile.module_name,
            "module_type": zeile.module_type,
            "version": zeile.version,
            "enabled": zeile.enabled,
            "country": getattr(quelle, "country", "") if quelle else "",
            "description": getattr(quelle, "description", "") if quelle else "",
            "default_exclude": getattr(quelle, "default_exclude", "") if quelle else "",
        })
    return ergebnis


@router.put("/modules/{module_name}/toggle")
async def toggle_module(module_name: str, enabled: bool, db: Session = Depends(get_db)):
    """Modul aktivieren/deaktivieren"""
    module = db.query(ModuleState).filter(ModuleState.module_name == module_name).first()
    if not module:
        raise HTTPException(status_code=404, detail=f"Module '{module_name}' not found")
    
    module.enabled = enabled
    db.commit()
    db.refresh(module)
    
    status = "✓ enabled" if enabled else "✗ disabled"
    return {"module": module_name, "status": status}


# Dashboard Overview
@router.get("/dashboard")
async def get_dashboard(db: Session = Depends(get_db)):
    """Dashboard-Übersicht"""
    config_count = db.query(Config).count()
    modules_enabled = db.query(ModuleState).filter(ModuleState.enabled == True).count()
    modules_total = db.query(ModuleState).count()
    
    return {
        "config_items": config_count,
        "modules": {
            "enabled": modules_enabled,
            "total": modules_total
        }
    }


# Cache Management
@router.post("/trigger-cache-sync")
async def trigger_cache_sync(db: Session = Depends(get_db)):
    """Manually trigger Mediathek cache sync"""
    try:
        from app.services.mediathek_direct import direct

        logger.info("🔄 Abgleich von Hand ausgeloest")
        await direct.sync_watchlist()

        return {"success": True, "message": "Abgleich abgeschlossen"}
    except Exception as e:
        logger.error(f"❌ Cache sync error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/logs")
async def get_logs(lines: int = Query(100, ge=1, le=1000)):
    """Get recent log entries from all rotated log files"""
    try:
        import glob
        from datetime import datetime

        # Get all log files (pbarr.log, pbarr.log.1, pbarr.log.2, etc.)
        log_pattern = "/app/app/pbarr.log*"
        log_files = sorted(glob.glob(log_pattern), reverse=True)  # Most recent first

        if not log_files:
            return {"logs": [], "message": "No log files found"}

        all_log_lines = []

        # Read all log files and collect lines with timestamps
        for log_file in log_files:
            if os.path.exists(log_file):
                try:
                    with open(log_file, 'r', encoding='utf-8') as f:
                        file_lines = f.readlines()
                        for line in file_lines:
                            line = line.strip()
                            if line:
                                # Extract timestamp from log line (format: YYYY-MM-DD HH:MM:SS)
                                try:
                                    timestamp_str = line.split(' - ')[0]
                                    timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                                    all_log_lines.append((timestamp, line))
                                except (ValueError, IndexError):
                                    # If timestamp parsing fails, add with current time as fallback
                                    all_log_lines.append((datetime.now(), line))
                except Exception as e:
                    logger.warning(f"Failed to read log file {log_file}: {e}")

        # Sort all lines by timestamp (most recent first)
        all_log_lines.sort(key=lambda x: x[0], reverse=True)

        # Get the most recent N lines
        recent_entries = all_log_lines[:lines]

        # Extract just the log text
        logs = [entry[1] for entry in recent_entries]

        return {"logs": logs, "total_lines": len(all_log_lines), "returned_lines": len(logs)}

    except Exception as e:
        logger.error(f"Log read error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read logs: {str(e)}")


@router.get("/logs/stream")
async def stream_logs():
    """Stream new log entries (Server-Sent Events)"""
    from fastapi.responses import StreamingResponse
    import asyncio
    import glob

    async def log_generator():
        # Monitor the main log file for new entries
        log_file = "/app/app/pbarr.log"

        last_size = 0
        last_rotation_check = 0

        while True:
            try:
                current_time = asyncio.get_event_loop().time()

                # Check for log rotation every 10 seconds
                if current_time - last_rotation_check > 10:
                    # If main log file was rotated, reset position
                    if os.path.exists(log_file):
                        current_size = os.path.getsize(log_file)
                        if current_size < last_size:
                            # File was likely rotated, reset to beginning
                            last_size = 0
                    last_rotation_check = current_time

                if os.path.exists(log_file):
                    current_size = os.path.getsize(log_file)
                    if current_size > last_size:
                        with open(log_file, 'r', encoding='utf-8') as f:
                            f.seek(last_size)
                            new_content = f.read()
                            if new_content.strip():
                                # Send new log lines
                                for line in new_content.strip().split('\n'):
                                    if line.strip():
                                        yield f"data: {line.strip()}\n\n"
                        last_size = current_size
                await asyncio.sleep(1)  # Check every second
            except Exception as e:
                logger.error(f"Log streaming error: {e}")
                yield f"data: ERROR: {str(e)}\n\n"
                await asyncio.sleep(5)  # Wait longer on error

    return StreamingResponse(
        log_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        }
    )




@router.get("/series")
async def get_series_list(db: Session = Depends(get_db)):
    """Get all series in watchlist with their filter settings"""
    try:
        series_list = db.query(WatchList).all()

        result = []
        for series in series_list:
            result.append({
                "tvdb_id": series.tvdb_id,
                "title": series.show_name,
                "sonarr_series_id": series.sonarr_series_id,
                "tagged_in_sonarr": series.tagged_in_sonarr,
                "import_source": series.import_source,
                "episodes_found": series.episodes_found,
                "mediathek_episodes_count": series.mediathek_episodes_count,
                "created_at": series.created_at.isoformat() if series.created_at else None,
                "last_accessed": series.last_accessed.isoformat() if series.last_accessed else None,
                # Filter fields
                "min_duration": series.min_duration,
                "max_duration": series.max_duration,
                "exclude_keywords": series.exclude_keywords,
                "library_folder": getattr(series, "library_folder", "") or "",
                "season_layout": getattr(series, "season_layout", "flat") or "flat",
                "include_senders": series.include_senders,
                "search_title_filter": series.search_title_filter,
                "custom_search_title": series.custom_search_title
            })

        return {"series": result}

    except Exception as e:
        logger.error(f"Error getting series list: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get series list: {str(e)}")


@router.put("/series/{tvdb_id}/filters")
async def update_series_filters(tvdb_id: str, filters: SeriesFiltersRequest, db: Session = Depends(get_db)):
    """Update filter settings for a specific series"""
    try:
        # Find the series
        series = db.query(WatchList).filter(WatchList.tvdb_id == tvdb_id).first()
        if not series:
            raise HTTPException(status_code=404, detail=f"Series with TVDB ID {tvdb_id} not found")

        # Update filter fields
        series.min_duration = filters.min_duration
        series.max_duration = filters.max_duration
        series.exclude_keywords = filters.exclude_keywords
        series.include_senders = filters.include_senders
        series.search_title_filter = filters.search_title_filter
        series.custom_search_title = filters.custom_search_title

        # Direkter Mediathek-Weg: nur setzen, wenn mitgeschickt. Die Felder
        # darueber werden bedingungslos ueberschrieben - ein Aufruf ohne diese
        # beiden wuerde sonst Qualitaet und Thema loeschen.
        if filters.quality is not None:
            series.quality = filters.quality
        if filters.search_topic is not None:
            series.search_topic = filters.search_topic
        if filters.library_folder is not None:
            series.library_folder = filters.library_folder.strip()
        if filters.season_layout is not None:
            series.season_layout = filters.season_layout.strip().lower()

        # Update last_accessed timestamp
        series.last_accessed = datetime.utcnow()

        db.commit()
        db.refresh(series)

        logger.info(f"✅ Updated filters for series {series.show_name} (TVDB: {tvdb_id})")

        # 🔄 AUTOMATIC CACHE INVALIDATION: Delete existing Mediathek cache for this series
        # since filters changed and cache needs to be rebuilt with new filters
        try:
            from app.models.mediathek_cache import MediathekCache

            deleted_count = db.query(MediathekCache).filter(
                MediathekCache.tvdb_id == tvdb_id
            ).delete()

            # Reset episode counts
            series.episodes_found = 0
            series.mediathek_episodes_count = 0
            db.commit()

            logger.info(f"🗑️ Deleted {deleted_count} cached Mediathek episodes for {series.show_name} due to filter changes")

            # Nach einer Filteraenderung sofort neu abgleichen. Die alte Fassung
            # baute hier einen Cache neu, den der direkte Weg nicht mehr benutzt.
            try:
                from app.services.mediathek_direct import direct
                import asyncio

                asyncio.create_task(direct.sync_entry(series, db))
                logger.info(f"🔄 Abgleich fuer '{series.show_name}' angestossen")

            except Exception as sync_error:
                logger.warning(f"Abgleich nicht angestossen: {sync_error}")
                # Die Filteraenderung selbst bleibt davon unberuehrt.

        except Exception as cache_error:
            logger.warning(f"Failed to clear cache after filter update: {cache_error}")
            # Don't fail the filter update if cache clearing fails

        return {
            "success": True,
            "message": f"Filters updated for series '{series.show_name}' - cache cleared and rebuild triggered",
            "series": {
                "tvdb_id": series.tvdb_id,
                "title": series.show_name,
                "min_duration": series.min_duration,
                "max_duration": series.max_duration,
                "exclude_keywords": series.exclude_keywords,
                "library_folder": getattr(series, "library_folder", "") or "",
                "season_layout": getattr(series, "season_layout", "flat") or "flat",
                "include_senders": series.include_senders
            },
            "cache_cleared": True,
            "cache_rebuild_triggered": True
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating series filters: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update filters: {str(e)}")


@router.delete("/series/{tvdb_id}")
async def delete_series_from_watchlist(tvdb_id: str, db: Session = Depends(get_db)):
    """Remove a series from the watchlist"""
    try:
        # Find the series
        series = db.query(WatchList).filter(WatchList.tvdb_id == tvdb_id).first()
        if not series:
            raise HTTPException(status_code=404, detail=f"Series with TVDB ID {tvdb_id} not found")

        series_name = series.show_name

        # Delete the series
        db.delete(series)
        db.commit()

        logger.info(f"✅ Deleted series {series_name} (TVDB: {tvdb_id}) from watchlist")

        return {
            "success": True,
            "message": f"Series '{series_name}' removed from watchlist"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting series: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete series: {str(e)}")





@router.post("/system/restart")
async def restart_container():
    """Request container restart (user must execute manually)."""
    logger.info("Container restart requested via admin panel")

    return {
        "status": "ok",
        "message": "Container-Neustart wurde angefordert. Führen Sie folgenden Befehl aus:",
        "command": "docker compose restart pbarr",
        "note": "Die Anwendung wird kurzzeitig nicht verfügbar sein."
    }


# ---------------------------------------------------------------------------
# Direct Mediathek path - no Sonarr, no TVDB
# ---------------------------------------------------------------------------

# German characters would otherwise be dropped entirely, turning "Groß" into
# "gro" and losing the difference to a hypothetical "Gros".
def _quellen_vorgabe_ausschluss(db) -> str:
    """
    Die Ausschlusswoerter der aktiven Quellen, zusammengefasst.

    Frueher stand hier fest "klare Sprache,Audiodeskription,Gebaerdensprache".
    Das sind die Bezeichnungen der deutschsprachigen Sender - ein Modul fuer ein
    anderes Land bringt seine eigenen mit und meldet sie ueber default_exclude an.
    """
    woerter = []
    for quelle in enabled_sources(db):
        for w in (getattr(quelle, "default_exclude", "") or "").split(","):
            w = w.strip()
            if w and w.lower() not in [x.lower() for x in woerter]:
                woerter.append(w)
    return ",".join(woerter)


def _umschrift(db) -> dict:
    """Sonderzeichen, die die aktiven Quellen ersetzt haben wollen."""
    tabelle = {}
    for quelle in enabled_sources(db):
        tabelle.update(getattr(quelle, "key_translit", {}) or {})
    return tabelle


def _topic_key(topic: str, umschrift: dict = None) -> str:
    """
    Einen stabilen internen Schluessel aus einem Sendungsnamen bilden.

    Akzente faltet der Kern selbst - é wird e, ñ wird n, å wird a. Das trifft
    fast jede europaeische Sprache. Zeichen ohne solche Zerlegung meldet die
    Quelle ueber key_translit an; im Deutschen sind das ae/oe/ue/ss, denn "Groß"
    wuerde sonst zu "gro" zusammenschrumpfen.

    Das Praefix "mvw:" ist historisch und bleibt, weil bestehende Merklisten
    darauf verweisen - es benennt keine Quelle mehr.
    """
    import re as _re
    import unicodedata

    text = (topic or "").lower()

    for zeichen, ersatz in (umschrift or {}).items():
        text = text.replace(zeichen.lower(), ersatz.lower())

    # Akzente abtrennen und verwerfen, den Grundbuchstaben behalten.
    text = "".join(
        z for z in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(z)
    )

    slug = _re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return f"mvw:{slug}"[:50]


@router.get("/mediathek/preview")
async def preview_mediathek_topic(
    topic: str = Query(..., description="Thema, wie es in der Mediathek heisst"),
    min_duration: int = Query(0),
    max_duration: int = Query(360),
    exclude_keywords: Optional[str] = Query(None),
    include_senders: str = Query(""),
    quality: str = Query("hd"),
    limit: int = Query(25),
    db: Session = Depends(get_db),
):
    """
    Show what a topic would pull in, before committing to it.

    This is the "simple search" - you type what the show is called and see what
    the Mediathek has under that name, with the filters already applied. No
    lookup step, no ids, no matching against a metadata source.
    """
    from app.services.mediathek_direct import direct

    # Mehrere Namen mit "|" trennen - genau wie sync_entry. Die Vorschau muss
    # dasselbe tun wie der spaetere Abgleich, sonst zeigt sie das Falsche.
    topics = [t.strip() for t in (topic or "").split("|") if t.strip()]
    items, seen = [], set()
    for t in topics:
        for item in await direct.search(t, db):
            if item.source_id not in seen:
                seen.add(item.source_id)
                items.append(item)

    # Nicht angegeben heisst: was die aktiven Quellen vorschlagen.
    ausschluss = (exclude_keywords if exclude_keywords is not None
                  else _quellen_vorgabe_ausschluss(db))

    out, kept, filtered = [], 0, 0

    for item in items:
        passes, reason = direct.passes_filters(
            item, min_duration, max_duration, ausschluss, include_senders
        )
        url, actual_quality = item.best_url(quality)
        if passes and url and not is_stream(url):
            kept += 1
        else:
            filtered += 1
        if len(out) < limit:
            season, episode = direct.extract_episode(item)
            out.append({
                "title": item.title,
                "channel": item.channel,
                "source": item.source,
                "aired": item.aired.strftime("%Y-%m-%d") if item.aired else None,
                "duration_minutes": round((item.duration_seconds or 0) / 60),
                "quality": actual_quality,
                "episode": f"S{season:02d}E{episode:02d}" if season is not None else None,
                "included": bool(passes and url and not is_stream(url)),
                "reason": (
                    ""
                    if (passes and url and not is_stream(url))
                    else (reason or ("nur als HLS-Stream, keine Datei"
                                     if url and is_stream(url)
                                     else "keine Video-URL"))
                ),
            })

    return {
        "topic": topic,
        "total": len(items),
        "included": kept,
        "filtered": filtered,
        "items": out,
    }


@router.post("/series/add-by-topic")
async def add_series_by_topic(request: AddByTopicRequest, db: Session = Depends(get_db)):
    """
    Add a show to the watchlist by its Mediathek topic name.

    Deliberately does no lookups. The old add-by-tvdb-id path needed TVDB to
    resolve a title and Sonarr to resolve a series id, which is exactly what
    kept public broadcasting shows out of the watchlist.
    """
    topic = (request.topic or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Ein Thema wird benoetigt")

    umschrift = _umschrift(db)
    key = _topic_key(topic, umschrift)
    if db.query(WatchList).filter(WatchList.tvdb_id == key).first():
        return {"success": False, "message": f"'{topic}' steht bereits auf der Liste"}

    # Auch gegen den Namen pruefen, nicht nur gegen den Schluessel.
    #
    # Eintraege aus der Zeit vor der Umstellung tragen eine TVDB-ID als
    # Schluessel, nicht "mvw:...". Ohne diese Pruefung liesse sich dieselbe
    # Sendung ein zweites Mal aufnehmen - beide Eintraege wuerden dann
    # dieselben Folgen in denselben Ordner laden.
    for vorhanden in db.query(WatchList).all():
        namen = [vorhanden.show_name or ""]
        namen += (getattr(vorhanden, "search_topic", "") or "").split("|")
        if any(_topic_key(n, umschrift) == key for n in namen if n.strip()):
            return {
                "success": False,
                "message": f"'{topic}' steht bereits als '{vorhanden.show_name}' auf der Liste",
            }

    entry = WatchList(
        tvdb_id=key,
        show_name=(request.display_name or topic.split("|")[0]).strip(),
        search_topic=topic,
        quality=request.quality or "hd",
        min_duration=request.min_duration,
        max_duration=request.max_duration,
        exclude_keywords=(request.exclude_keywords
                          if request.exclude_keywords is not None
                          else _quellen_vorgabe_ausschluss(db)),
        include_senders=request.include_senders,
        library_folder=(request.library_folder or "").strip(),
        season_layout=(request.season_layout or "flat").strip().lower(),
        import_source="mediathek",
        tagged_in_sonarr=False,
    )
    db.add(entry)
    db.commit()

    logger.info(f"➕ '{topic}' zur Watch-List hinzugefuegt (key={key})")
    return {
        "success": True,
        "message": f"'{topic}' hinzugefuegt",
        "key": key,
        "show_name": entry.show_name,
    }


@router.post("/series/{watch_key:path}/sync")
async def sync_single_series(watch_key: str, db: Session = Depends(get_db)):
    """Fetch what is new for one watchlist entry, right now."""
    from app.services.mediathek_direct import direct

    entry = db.query(WatchList).filter(WatchList.tvdb_id == watch_key).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")

    fetched = await direct.sync_entry(entry, db)
    return {"success": True, "show_name": entry.show_name, "fetched": fetched}
