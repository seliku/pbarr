from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
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
from app.services.sonarr_wizard import SonarrSetupWizard
from app.services.sonarr_webhook import SonarrWebhookManager
from app.services.mediathek_importer import importer


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

    class Config:
        from_attributes = True


class TestConnectionRequest(BaseModel):
    sonarr_url: str
    api_key: str
    pbarr_url: str
    sonarr_download_path: Optional[str] = None


class SetupRequest(BaseModel):
    sonarr_url: str
    api_key: str
    pbarr_url: str
    sonarr_download_path_host: str


class WebhookSetupRequest(BaseModel):
    sonarr_url: str
    api_key: str
    pbarr_url: str


class AddSeriesRequest(BaseModel):
    tvdb_id: str
    title: Optional[str] = None


class SeriesFiltersRequest(BaseModel):
    min_duration: Optional[int] = None
    max_duration: Optional[int] = None
    exclude_keywords: Optional[str] = None
    include_senders: Optional[str] = None


# HTML Admin Panel
@router.get("/")
async def admin_panel():
    """Serve admin.html"""
    admin_html = os.path.join(os.path.dirname(__file__), "..", "static", "admin.html")
    if os.path.exists(admin_html):
        return FileResponse(admin_html, media_type="text/html")
    return {"error": "Admin panel not found"}


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

    # SOCKS5 Proxy validation
    if key == "socks5_proxy" and update.value and update.value.strip():
        from app.utils.network import parse_socks5_proxy
        parsed = parse_socks5_proxy(update.value.strip())
        if not parsed:
            raise HTTPException(
                status_code=400,
                detail="Invalid SOCKS5 proxy format. Use: host:port or host:port:user:pass or socks5://host:port"
            )

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

    # SOCKS5 Proxy cache invalidation
    if key == "socks5_proxy":
        from app.utils.network import clear_proxy_cache
        clear_proxy_cache()
        logger.info("SOCKS5 proxy cache cleared due to configuration change")

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
    modules = db.query(ModuleState).all()
    return modules


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
        from app.services.mediathek_cacher import cacher

        logger.info("🔄 Manual cache sync triggered")
        await cacher.sync_watched_shows()

        return {"success": True, "message": "Cache sync completed"}
    except Exception as e:
        logger.error(f"❌ Cache sync error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/trigger-import-scan")
async def trigger_import_scan(db: Session = Depends(get_db)):
    """Synchronize PBArr watchlist with Sonarr series that have the 'pbarr' tag"""
    try:
        logger.info("🔄 Starting Sonarr import scan - syncing series with 'pbarr' tag")

        # Get Sonarr config
        sonarr_url_config = db.query(Config).filter_by(key="sonarr_url").first()
        sonarr_api_config = db.query(Config).filter_by(key="sonarr_api_key").first()

        if not sonarr_url_config or not sonarr_url_config.value:
            raise HTTPException(status_code=400, detail="Sonarr URL not configured")
        if not sonarr_api_config or not sonarr_api_config.value:
            raise HTTPException(status_code=400, detail="Sonarr API key not configured")

        sonarr_manager = SonarrWebhookManager(sonarr_url_config.value, sonarr_api_config.value)

        # Step 1: Get PBArr tag ID
        pbarr_tag_id = await sonarr_manager._get_or_create_pbarr_tag()
        if not pbarr_tag_id:
            raise HTTPException(status_code=500, detail="Could not get/create PBArr tag in Sonarr")

        logger.info(f"PBArr tag ID: {pbarr_tag_id}")

        # Step 2: Get all series from Sonarr
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{sonarr_manager.sonarr_url}/api/v3/series",
                headers=sonarr_manager.headers
            )

            if resp.status_code != 200:
                raise HTTPException(status_code=500, detail=f"Failed to get series from Sonarr: HTTP {resp.status_code}")

            sonarr_series = resp.json()

        logger.info(f"Found {len(sonarr_series)} series in Sonarr")

        # Step 3: Identify series with PBArr tag
        series_with_tag = []
        series_without_tag = []

        for series in sonarr_series:
            series_tags = series.get("tags", [])
            tvdb_id = str(series.get("tvdbId", ""))

            if pbarr_tag_id in series_tags and tvdb_id:
                series_with_tag.append({
                    "tvdb_id": tvdb_id,
                    "title": series.get("title", "Unknown"),
                    "sonarr_id": series.get("id"),
                    "tags": series_tags
                })
            elif tvdb_id:
                series_without_tag.append({
                    "tvdb_id": tvdb_id,
                    "title": series.get("title", "Unknown"),
                    "sonarr_id": series.get("id")
                })

        logger.info(f"Series with PBArr tag: {len(series_with_tag)}")
        logger.info(f"Series without PBArr tag: {len(series_without_tag)}")

        # Step 4: Process series with PBArr tag (add to watchlist if not already there)
        added_count = 0
        updated_count = 0

        for series_data in series_with_tag:
            tvdb_id = series_data["tvdb_id"]
            title = series_data["title"]
            sonarr_id = series_data["sonarr_id"]

            # Check if already in watchlist
            existing = db.query(WatchList).filter(WatchList.tvdb_id == tvdb_id).first()

            if existing:
                # Update if not already tagged
                if not existing.tagged_in_sonarr:
                    existing.tagged_in_sonarr = True
                    existing.sonarr_series_id = sonarr_id
                    updated_count += 1
                    logger.info(f"✓ Updated existing series: {title} (TVDB: {tvdb_id})")
                else:
                    logger.debug(f"Series already tagged: {title} (TVDB: {tvdb_id})")
            else:
                # Add new series
                watchlist_entry = WatchList(
                    tvdb_id=tvdb_id,
                    show_name=title,
                    sonarr_series_id=sonarr_id,
                    import_source="sonarr_import",
                    tagged_in_sonarr=True
                )
                db.add(watchlist_entry)
                added_count += 1
                logger.info(f"✓ Added new series: {title} (TVDB: {tvdb_id})")

        # Step 5: Process series without PBArr tag (remove from watchlist and clean up all related data)
        removed_count = 0

        for series_data in series_without_tag:
            tvdb_id = series_data["tvdb_id"]
            title = series_data["title"]

            # Check if in watchlist and was previously tagged
            existing = db.query(WatchList).filter(
                WatchList.tvdb_id == tvdb_id,
                WatchList.tagged_in_sonarr == True
            ).first()

            if existing:
                # Remove from watchlist since tag was removed
                db.delete(existing)
                removed_count += 1
                logger.info(f"✗ Removed series (tag removed): {title} (TVDB: {tvdb_id})")

                # Clean up all related data for this series
                try:
                    # Remove all TVDB cache entries
                    from app.models.tvdb_cache import TVDBCache
                    tvdb_deleted = db.query(TVDBCache).filter(TVDBCache.tvdb_id == tvdb_id).delete()
                    logger.info(f"  🗑️ Removed {tvdb_deleted} TVDB cache entries for {title}")

                    # Remove all Mediathek cache entries
                    from app.models.mediathek_cache import MediathekCache
                    mediathek_deleted = db.query(MediathekCache).filter(MediathekCache.tvdb_id == tvdb_id).delete()
                    logger.info(f"  🗑️ Removed {mediathek_deleted} Mediathek cache entries for {title}")

                    # Remove all episode monitoring state
                    from app.models.episode_monitoring_state import EpisodeMonitoringState
                    monitoring_deleted = db.query(EpisodeMonitoringState).filter(
                        EpisodeMonitoringState.sonarr_series_id == existing.sonarr_series_id
                    ).delete()
                    logger.info(f"  🗑️ Removed {monitoring_deleted} episode monitoring entries for {title}")

                    logger.info(f"  ✅ Complete cleanup finished for {title}")

                except Exception as cleanup_error:
                    logger.error(f"  ❌ Error during cleanup for {title}: {cleanup_error}")
                    # Continue with next series even if cleanup fails

        # Step 6: Commit all changes
        db.commit()

        # Step 7: Trigger cache sync for all tagged series
        try:
            from app.services.mediathek_cacher import cacher
            await cacher.sync_watched_shows()
            logger.info("✓ Triggered cache sync for all tagged series")
        except Exception as e:
            logger.warning(f"Failed to trigger cache sync: {e}")

        # Summary
        total_processed = len(series_with_tag) + len(series_without_tag)
        summary = f"Import scan completed: {added_count} added, {updated_count} updated, {removed_count} removed from {total_processed} total Sonarr series"

        logger.info(f"✅ {summary}")

        return {
            "success": True,
            "message": summary,
            "statistics": {
                "total_sonarr_series": len(sonarr_series),
                "series_with_tag": len(series_with_tag),
                "series_without_tag": len(series_without_tag),
                "added_to_watchlist": added_count,
                "updated_in_watchlist": updated_count,
                "removed_from_watchlist": removed_count
            },
            "cache_sync_triggered": True
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Import scan error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync-tvdb")
async def sync_tvdb(tvdb_id: str = Query(...), db: Session = Depends(get_db)):
    """Manually sync TVDB episodes for a show"""
    try:
        from app.services.tvdb_client import TVDBClient

        tvdb_key_config = db.query(Config).filter_by(key="tvdb_api_key").first()
        if not tvdb_key_config or not tvdb_key_config.value:
            raise HTTPException(status_code=400, detail="TVDB API key not configured")

        logger.info(f"🔄 Syncing TVDB for {tvdb_id}")

        tvdb_client = TVDBClient(tvdb_key_config.value, db=db)
        episodes = await tvdb_client.get_episodes(tvdb_id)

        return {"success": True, "episodes": len(episodes), "message": f"Synced {len(episodes)} episodes"}

    except Exception as e:
        logger.error(f"TVDB sync error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/logs")
async def get_logs(lines: int = Query(100, ge=1, le=1000)):
    """Get recent log entries from all rotated log files"""
    try:
        import glob
        from datetime import datetime

        # Get all log files (pbarr.log, pbarr.log.1, pbarr.log.2, etc.)
        log_pattern = "/app/logs/pbarr.log*"
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
        log_file = "/app/logs/pbarr.log"

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


# Sonarr Integration Setup Wizard
@router.post("/sonarr/test-connection")
async def test_sonarr_connection(request: TestConnectionRequest, db: Session = Depends(get_db)):
    """Test Sonarr connection and save config if successful"""
    wizard = SonarrSetupWizard(request.sonarr_url, request.api_key)
    result = await wizard.test_connection()

    # Save config if successful
    if result.get("success"):
        configs = [
            ("sonarr_url", request.sonarr_url),
            ("sonarr_api_key", request.api_key),
            ("pbarr_url", request.pbarr_url)  # User-provided PBArr URL
        ]

        # Only save download path if provided
        if request.sonarr_download_path:
            configs.append(("sonarr_download_path", request.sonarr_download_path))

        for key, value in configs:
            config = db.query(Config).filter_by(key=key).first()
            if config:
                config.value = str(value)
            else:
                config = Config(key=key, value=str(value))
                db.add(config)
        db.commit()
        logger.info("Sonarr connection test successful - config saved")

    return result


@router.get("/sonarr/config")
async def get_sonarr_config(db: Session = Depends(get_db)):
    """Get saved Sonarr configuration"""
    config_keys = ["sonarr_url", "sonarr_api_key", "pbarr_url"]
    config_data = {}

    for key in config_keys:
        config = db.query(Config).filter_by(key=key).first()
        if config:
            config_data[key] = config.value

    # Add hardcoded download path info
    config_data["download_path_info"] = {
        "container_path": "/app/downloads/completed",
        "description": "PBArr downloads to this fixed path in the container. Configure the host mapping in docker-compose.yml"
    }

    return config_data


@router.post("/sonarr/setup")
async def setup_sonarr(request: SetupRequest, db: Session = Depends(get_db)):
    """Execute complete Sonarr setup"""
    logger.info(f"Setup request received: {request.dict()}")
    wizard = SonarrSetupWizard(request.sonarr_url, request.api_key)
    results = await wizard.setup_all(request.pbarr_url, request.sonarr_download_path_host)

    # Save config if successful
    if results.get("success"):
        configs = [
            ("sonarr_url", request.sonarr_url),
            ("sonarr_api_key", request.api_key),
            ("pbarr_url", request.pbarr_url),
            ("sonarr_download_path_host", request.sonarr_download_path_host)
        ]
        for key, value in configs:
            config = db.query(Config).filter_by(key=key).first()
            if config:
                config.value = str(value)
            else:
                config = Config(key=key, value=str(value))
                db.add(config)
        db.commit()

    return results


@router.get("/sonarr/status")
async def get_sonarr_status(db: Session = Depends(get_db)):
    """Check Sonarr configuration and integration status"""
    try:
        # Get saved config
        sonarr_url_config = db.query(Config).filter_by(key="sonarr_url").first()
        sonarr_api_config = db.query(Config).filter_by(key="sonarr_api_key").first()

        status = {
            "config_complete": False,
            "connection_ok": False,
            "download_client_exists": False,
            "indexer_exists": False,
            "message": "",
            "setup_needed": True
        }

        # Check if config is complete
        if not sonarr_url_config or not sonarr_url_config.value or not sonarr_api_config or not sonarr_api_config.value:
            status["message"] = "Sonarr URL und API-Key müssen konfiguriert werden"
            return status

        status["config_complete"] = True

        # Test connection
        wizard = SonarrSetupWizard(sonarr_url_config.value, sonarr_api_config.value)
        connection_result = await wizard.test_connection()

        if not connection_result.get("success"):
            status["message"] = f"Verbindung zu Sonarr fehlgeschlagen: {connection_result.get('message')}"
            return status

        status["connection_ok"] = True

        # Check if PBArr download client exists
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{wizard.url}/api/v3/downloadclient",
                    headers=wizard.headers
                )
                if resp.status_code == 200:
                    clients = resp.json()
                    logger.info(f"Found {len(clients)} download clients")
                    for client in clients:
                        client_name = client.get("name")
                        logger.info(f"Download client: {client_name}")
                        if client_name == "PBArr":
                            status["download_client_exists"] = True
                            logger.info("PBArr download client found!")
                            break
                else:
                    logger.warning(f"Download client check failed: HTTP {resp.status_code}")
        except Exception as e:
            logger.warning(f"Failed to check download clients: {e}")

        # Check if PBArr indexer exists
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{wizard.url}/api/v3/indexer",
                    headers=wizard.headers
                )
                if resp.status_code == 200:
                    indexers = resp.json()
                    logger.info(f"Found {len(indexers)} indexers")
                    for indexer in indexers:
                        indexer_name = indexer.get("name")
                        logger.info(f"Indexer: {indexer_name}")
                        if indexer_name == "PBArr":
                            status["indexer_exists"] = True
                            logger.info("PBArr indexer found!")
                            break
                else:
                    logger.warning(f"Indexer check failed: HTTP {resp.status_code}")
        except Exception as e:
            logger.warning(f"Failed to check indexers: {e}")

        logger.info(f"Status check result: download_client={status['download_client_exists']}, indexer={status['indexer_exists']}")

        # Determine final status
        pbarr_configured = status["download_client_exists"] and status["indexer_exists"]

        if pbarr_configured:
            status["setup_needed"] = False
            status["message"] = "Sonarr ist für PBArr konfiguriert und erreichbar."
        else:
            status["setup_needed"] = True
            status["message"] = "Sonarr ist noch nicht für PBArr konfiguriert."

        return status

    except Exception as e:
        logger.error(f"Sonarr status check error: {e}", exc_info=True)
        return {
            "config_complete": False,
            "connection_ok": False,
            "download_client_exists": False,
            "indexer_exists": False,
            "message": f"Fehler beim Status-Check: {str(e)}",
            "setup_needed": True
        }


# New Webhook-based Sonarr Integration
@router.post("/sonarr/webhook/setup")
async def setup_sonarr_webhook(request: WebhookSetupRequest, db: Session = Depends(get_db)):
    """Setup Sonarr webhook for automatic series addition"""
    logger.info(f"Webhook setup request received: {request.dict()}")

    # Test connection first
    webhook_manager = SonarrWebhookManager(request.sonarr_url, request.api_key)
    wizard = SonarrSetupWizard(request.sonarr_url, request.api_key)
    connection_result = await wizard.test_connection()

    if not connection_result.get("success"):
        return {
            "success": False,
            "message": f"❌ Sonarr-Verbindung fehlgeschlagen: {connection_result.get('message')}"
        }

    # Create webhook
    webhook_result = await webhook_manager.create_webhook(request.pbarr_url)

    if not webhook_result.get("success"):
        return webhook_result

    # Test webhook connection
    test_result = await webhook_manager.test_webhook_connection(request.pbarr_url)
    if not test_result.get("success"):
        logger.warning(f"Webhook connection test failed: {test_result.get('message')}")
        # Don't fail setup if test fails, just warn

    # Save config
    configs = [
        ("sonarr_url", request.sonarr_url),
        ("sonarr_api_key", request.api_key),
        ("pbarr_url", request.pbarr_url)
    ]
    for key, value in configs:
        config = db.query(Config).filter_by(key=key).first()
        if config:
            config.value = str(value)
        else:
            config = Config(key=key, value=str(value))
            db.add(config)
    db.commit()

    # Automatically import existing series from Sonarr
    import_result = None
    try:
        logger.info("Starting automatic import of existing Sonarr series...")
        import_result = await importer.import_existing_series_from_sonarr(
            request.sonarr_url,
            request.api_key,
            db
        )
        logger.info(f"Automatic import completed: {import_result['imported']} imported, {import_result['skipped']} skipped")
    except Exception as e:
        logger.error(f"Automatic import failed: {e}")
        import_result = {"imported": 0, "skipped": 0, "total": 0, "errors": [str(e)]}

    return {
        "success": True,
        "message": "✓ Webhook in Sonarr erfolgreich konfiguriert und bestehende Serien importiert",
        "webhook_id": webhook_result.get("webhook_id"),
        "connection_test": test_result.get("message", "Test nicht durchgeführt"),
        "automatic_import": {
            "imported": import_result["imported"],
            "skipped": import_result["skipped"],
            "total": import_result["total"],
            "errors": import_result["errors"] if import_result["errors"] else []
        }
    }


@router.get("/sonarr/webhook/status")
async def get_sonarr_webhook_status(db: Session = Depends(get_db)):
    """Check Sonarr webhook configuration status"""
    try:
        # Get saved config
        sonarr_url_config = db.query(Config).filter_by(key="sonarr_url").first()
        sonarr_api_config = db.query(Config).filter_by(key="sonarr_api_key").first()

        status = {
            "config_complete": False,
            "connection_ok": False,
            "webhook_exists": False,
            "message": "",
            "setup_needed": True
        }

        # Check if config is complete
        if not sonarr_url_config or not sonarr_url_config.value or not sonarr_api_config or not sonarr_api_config.value:
            status["message"] = "Sonarr URL und API-Key müssen konfiguriert werden"
            return status

        status["config_complete"] = True

        # Test connection
        wizard = SonarrSetupWizard(sonarr_url_config.value, sonarr_api_config.value)
        connection_result = await wizard.test_connection()

        if not connection_result.get("success"):
            status["message"] = f"Verbindung zu Sonarr fehlgeschlagen: {connection_result.get('message')}"
            return status

        status["connection_ok"] = True

        # Check if PBArr webhook exists
        webhook_manager = SonarrWebhookManager(sonarr_url_config.value, sonarr_api_config.value)
        existing_webhook = await webhook_manager._get_existing_webhook()

        if existing_webhook:
            status["webhook_exists"] = True
            status["setup_needed"] = False
            status["message"] = "Sonarr Webhook ist konfiguriert und erreichbar."
        else:
            status["setup_needed"] = True
            status["message"] = "Sonarr Webhook ist noch nicht konfiguriert."

        return status

    except Exception as e:
        logger.error(f"Sonarr webhook status check error: {e}", exc_info=True)
        return {
            "config_complete": False,
            "connection_ok": False,
            "webhook_exists": False,
            "message": f"Fehler beim Webhook-Status-Check: {str(e)}",
            "setup_needed": True
        }


# Import existing series from Sonarr
@router.post("/sonarr/import-existing-series")
async def import_existing_sonarr_series(db: Session = Depends(get_db)):
    """Import existing series from Sonarr that have mediathek content"""
    try:
        logger.info("Starting import of existing series from Sonarr")

        # Get saved config
        sonarr_url_config = db.query(Config).filter_by(key="sonarr_url").first()
        sonarr_api_config = db.query(Config).filter_by(key="sonarr_api_key").first()

        if not sonarr_url_config or not sonarr_url_config.value:
            raise HTTPException(status_code=400, detail="Sonarr URL not configured")
        if not sonarr_api_config or not sonarr_api_config.value:
            raise HTTPException(status_code=400, detail="Sonarr API key not configured")

        # Run import
        result = await importer.import_existing_series_from_sonarr(
            sonarr_url_config.value,
            sonarr_api_config.value,
            db
        )

        logger.info(f"Import completed: {result['imported']} imported, {result['skipped']} skipped")

        return {
            "success": True,
            "imported": result["imported"],
            "skipped": result["skipped"],
            "total": result["total"],
            "errors": result["errors"],
            "message": f"Import abgeschlossen: {result['imported']} Serien hinzugefügt, {result['skipped']} übersprungen"
        }

    except Exception as e:
        logger.error(f"Import error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")


# Manually add series to watchlist
@router.post("/series/add")
async def add_series_to_watchlist(request: AddSeriesRequest, db: Session = Depends(get_db)):
    """Manually add a series to the watchlist with proper Sonarr integration"""
    try:
        tvdb_id = request.tvdb_id.strip()
        if not tvdb_id:
            raise HTTPException(status_code=400, detail="TVDB ID is required")

        # Check if series already exists
        existing = db.query(WatchList).filter(WatchList.tvdb_id == tvdb_id).first()
        if existing:
            return {
                "success": False,
                "message": f"Series with TVDB ID {tvdb_id} already exists in watchlist"
            }

        # Get series title from request or try to get from TVDB
        title = request.title
        if not title:
            # Try to get title from TVDB cache
            from app.models.tvdb_cache import TVDBCache
            tvdb_entry = db.query(TVDBCache).filter(TVDBCache.tvdb_id == tvdb_id).first()
            if tvdb_entry:
                # Get show name from the first episode (they all have the same show name)
                title = tvdb_entry.show_name
            else:
                # Fallback: try to sync TVDB first
                try:
                    from app.services.tvdb_client import TVDBClient
                    tvdb_key_config = db.query(Config).filter_by(key="tvdb_api_key").first()
                    if tvdb_key_config and tvdb_key_config.value:
                        tvdb_client = TVDBClient(tvdb_key_config.value, db=db)
                        episodes = await tvdb_client.get_episodes(tvdb_id)
                        if episodes:
                            title = episodes[0].get("show_name", f"TVDB-{tvdb_id}")
                        else:
                            title = f"TVDB-{tvdb_id}"
                    else:
                        title = f"TVDB-{tvdb_id}"
                except Exception as e:
                    logger.warning(f"Could not get title from TVDB: {e}")
                    title = f"TVDB-{tvdb_id}"

        # Try to find sonarr_series_id from Sonarr
        sonarr_series_id = None
        sonarr_url_config = db.query(Config).filter_by(key="sonarr_url").first()
        sonarr_api_config = db.query(Config).filter_by(key="sonarr_api_key").first()

        if sonarr_url_config and sonarr_api_config and sonarr_url_config.value and sonarr_api_config.value:
            try:
                # Query Sonarr for series with this TVDB ID
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        f"{sonarr_url_config.value}/api/v3/series",
                        headers={"X-Api-Key": sonarr_api_config.value}
                    )

                    if resp.status_code == 200:
                        sonarr_series = resp.json()
                        # Find series with matching TVDB ID
                        for series in sonarr_series:
                            if str(series.get("tvdbId", "")) == tvdb_id:
                                sonarr_series_id = series.get("id")
                                logger.info(f"Found Sonarr series ID {sonarr_series_id} for TVDB {tvdb_id}")
                                break

                        if not sonarr_series_id:
                            logger.warning(f"Series with TVDB ID {tvdb_id} not found in Sonarr")
                    else:
                        logger.warning(f"Failed to query Sonarr series: HTTP {resp.status_code}")

            except Exception as e:
                logger.warning(f"Error querying Sonarr for series ID: {e}")

        # Add to watchlist
        watchlist_entry = WatchList(
            tvdb_id=tvdb_id,
            show_name=title,
            sonarr_series_id=sonarr_series_id,
            import_source="manual"
        )

        db.add(watchlist_entry)
        db.commit()
        db.refresh(watchlist_entry)

        logger.info(f"✅ Added series {title} (TVDB: {tvdb_id}) to watchlist with sonarr_series_id={sonarr_series_id}")

        # Trigger immediate cache sync for this series
        try:
            from app.services.mediathek_cacher import cacher
            await cacher.sync_watched_shows()
        except Exception as e:
            logger.warning(f"Failed to trigger cache sync: {e}")

        return {
            "success": True,
            "message": f"Series '{title}' added to watchlist",
            "series": {
                "tvdb_id": tvdb_id,
                "title": title,
                "sonarr_series_id": sonarr_series_id,
                "import_source": "manual"
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding series to watchlist: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to add series: {str(e)}")


# Series Management Endpoints
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
                "include_senders": series.include_senders
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

            # 🔄 AUTOMATIC CACHE REBUILD: Trigger immediate cache rebuild with new filters
            try:
                from app.services.mediathek_cacher import cacher
                import asyncio

                # Run cache rebuild in background (don't await to avoid blocking response)
                asyncio.create_task(cacher.cache_series(tvdb_id, series.show_name))

                logger.info(f"🔄 Triggered cache rebuild for {series.show_name} with new filters")

            except Exception as cache_error:
                logger.warning(f"Failed to trigger cache rebuild: {cache_error}")
                # Don't fail the filter update if cache rebuild fails

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


# SOCKS5 Proxy Testing
@router.post("/test-proxy")
async def test_proxy_connection():
    """Test SOCKS5 proxy connectivity."""
    from app.utils.network import test_socks5_proxy
    result = await test_socks5_proxy()
    return result


# Enhanced Settings API
@router.post("/settings")
async def update_settings(settings: dict):
    """Update admin settings with validation."""
    from app.database import SessionLocal
    from app.models.config import Config
    from app.utils.network import parse_socks5_proxy, clear_proxy_cache

    db = SessionLocal()

    try:
        if "socks5_proxy" in settings:
            proxy_value = settings["socks5_proxy"]

            if proxy_value and proxy_value.strip():
                # Validate format
                parsed = parse_socks5_proxy(proxy_value)
                if not parsed:
                    return {
                        "error": f"Invalid SOCKS5 proxy format: {proxy_value}",
                        "hint": "Format: 'host:port' or 'socks5://host:port' or 'user:pass@host:port'"
                    }

                # Save to DB
                config = db.query(Config).filter_by(key="socks5_proxy").first()
                if config:
                    config.value = proxy_value
                else:
                    config = Config(key="socks5_proxy", value=proxy_value)
                    db.add(config)
                db.commit()

                # Clear cache so new proxy takes effect immediately
                clear_proxy_cache()

                logger.info(f"SOCKS5 proxy setting updated: {parsed['host']}:{parsed['port']}")

                return {
                    "status": "ok",
                    "message": f"Proxy setting saved: {parsed['host']}:{parsed['port']}"
                }
            else:
                # Clear proxy setting
                config = db.query(Config).filter_by(key="socks5_proxy").first()
                if config:
                    db.delete(config)
                    db.commit()

                # Clear cache
                clear_proxy_cache()

                logger.info("SOCKS5 proxy setting cleared")

                return {
                    "status": "ok",
                    "message": "Proxy setting cleared"
                }

        return {"error": "Unknown setting"}

    except Exception as e:
        logger.error(f"Settings update error: {e}")
        return {"error": f"Failed to update settings: {str(e)}"}
    finally:
        db.close()
