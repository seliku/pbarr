from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List, Dict
import logging

from app.database import get_db
from app.models.watch_list import WatchList
from app.models.mediathek_cache import MediathekCache
from app.models.config import Config
from app.services.sonarr_webhook import SonarrWebhookManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/")
async def get_dashboard(db: Session = Depends(get_db)):
    """
    Get dashboard data showing Sonarr integration statistics and series status
    """
    try:
        # Get all watchlist entries
        watchlist_entries = db.query(WatchList).all()

        # Calculate summary statistics
        total_series = len(watchlist_entries)
        # handled_by_pbarr = series that have mediathek content available
        handled_by_pbarr = sum(1 for entry in watchlist_entries if entry.mediathek_episodes_count > 0)
        tagged_series = sum(1 for entry in watchlist_entries if entry.tagged_in_sonarr)
        imported_series = sum(1 for entry in watchlist_entries if entry.import_source == "sonarr_import")

        # Calculate percentage (avoid division by zero)
        percentage = (handled_by_pbarr / total_series * 100) if total_series > 0 else 0

        # Get latest import time
        latest_import = None
        if watchlist_entries:
            # Find the most recent created_at for imported series
            imported_entries = [entry for entry in watchlist_entries if entry.import_source == "sonarr_import"]
            if imported_entries:
                latest_import = max(entry.created_at for entry in imported_entries)
            else:
                # If no manual imports, check if webhook is set up (treat as "automatic import enabled")
                try:
                    from app.models.config import Config
                    webhook_config = db.query(Config).filter_by(key="pbarr_url").first()
                    if webhook_config and webhook_config.updated_at:
                        # Use webhook setup time as "latest import" for automatic imports
                        latest_import = webhook_config.updated_at
                except Exception:
                    pass

        # Get Sonarr config for episode status checks
        sonarr_url_config = db.query(Config).filter_by(key="sonarr_url").first()
        sonarr_api_config = db.query(Config).filter_by(key="sonarr_api_key").first()
        sonarr_configured = (sonarr_url_config and sonarr_api_config and
                           sonarr_url_config.value and sonarr_api_config.value)

        sonarr_manager = None
        if sonarr_configured:
            sonarr_manager = SonarrWebhookManager(sonarr_url_config.value, sonarr_api_config.value)

        # Build series list with current status
        series_list = []
        cutoff_date = datetime.utcnow() - timedelta(days=30)  # Consider recent episodes

        for entry in watchlist_entries:
            # Count episodes found in mediathek
            episode_count = db.query(MediathekCache).filter(
                MediathekCache.tvdb_id == entry.tvdb_id,
                MediathekCache.expires_at > datetime.utcnow()
            ).count()

            # Check if series has recent episodes available
            recent_episodes = db.query(MediathekCache).filter(
                MediathekCache.tvdb_id == entry.tvdb_id,
                MediathekCache.created_at > cutoff_date,
                MediathekCache.expires_at > datetime.utcnow()
            ).count()

            # Find latest episode found
            latest_episode = db.query(MediathekCache).filter(
                MediathekCache.tvdb_id == entry.tvdb_id,
                MediathekCache.expires_at > datetime.utcnow()
            ).order_by(MediathekCache.created_at.desc()).first()

            latest_episode_date = latest_episode.created_at if latest_episode else None

            # Calculate missing monitored episodes (only if Sonarr is configured and series has sonarr_series_id)
            missing_monitored = 0
            total_monitored = 0
            has_file_count = 0
            unmonitored_count = 0

            if sonarr_manager and entry.sonarr_series_id:
                try:
                    # Get all episodes from Sonarr for this series
                    all_episodes = await sonarr_manager.get_all_monitored_episodes(entry.sonarr_series_id)
                    total_monitored = len(all_episodes)

                    # Count episodes with files
                    has_file_count = sum(1 for ep in all_episodes if ep.get("hasFile", False))

                    # Missing monitored episodes = total monitored - episodes with files
                    missing_monitored = total_monitored - has_file_count

                    # Calculate unmonitored episodes (total episodes in series - monitored)
                    # This is approximate since we don't have total episode count from Sonarr
                    # For now, we'll leave it as 0 or calculate differently if needed

                except Exception as e:
                    logger.warning(f"Could not get episode status for {entry.show_name}: {e}")
                    missing_monitored = 0
                    total_monitored = 0
                    has_file_count = 0

            series_data = {
                "title": entry.show_name,
                "tvdb_id": int(entry.tvdb_id),
                "sonarr_series_id": entry.sonarr_series_id,
                "status": "continuing",  # Could be enhanced to check actual status
                "added_to_pbarr": entry.created_at.isoformat(),
                "latest_episode_found": latest_episode_date.isoformat() if latest_episode_date else None,
                "in_mediathek_now": recent_episodes > 0,
                "mediathek_episodes_count": episode_count,
                "tagged_in_sonarr": entry.tagged_in_sonarr,
                "import_source": entry.import_source,
                # New fields for accurate episode status
                "total_monitored": total_monitored,
                "has_file": has_file_count,
                "missing_monitored": missing_monitored,
                "unmonitored": unmonitored_count
            }
            series_list.append(series_data)

        # Sort by latest episode found (most recent first)
        series_list.sort(
            key=lambda x: x["latest_episode_found"] or "1970-01-01",
            reverse=True
        )

        # Build response
        response = {
            "summary": {
                "total_in_sonarr": total_series,
                "handled_by_pbarr": handled_by_pbarr,
                "percentage": round(percentage, 1),
                "latest_import": latest_import.isoformat() if latest_import else None
            },
            "series": series_list
        }

        return response

    except Exception as e:
        logger.error(f"Dashboard error: {e}", exc_info=True)
        return {
            "summary": {
                "total_in_sonarr": 0,
                "handled_by_pbarr": 0,
                "percentage": 0,
                "latest_import": None
            },
            "series": [],
            "error": str(e)
        }
