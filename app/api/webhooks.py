from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
import logging

from app.database import get_db
from app.models.watch_list import WatchList
from app.services.mediathek_cacher import cacher
from app.services.sonarr_webhook import SonarrWebhookManager
from app.models.config import Config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhooks"])


class SonarrWebhookPayload(BaseModel):
    """Sonarr Webhook Payload Schema"""
    eventType: str
    series: dict
    episodes: Optional[list] = None


@router.post("/sonarr")
async def sonarr_webhook(
    payload: SonarrWebhookPayload,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Handle Sonarr webhooks for series additions
    """
    try:
        logger.info(f"Received Sonarr webhook: {payload.eventType}")

        # Process SeriesAdd/SeriesAdded and SeriesDelete events
        if payload.eventType not in ["SeriesAdd", "SeriesAdded", "SeriesDelete"]:
            logger.info(f"Ignoring webhook event: {payload.eventType}")
            return {"status": "ignored", "event": payload.eventType}

        series_data = payload.series
        tvdb_id = str(series_data.get("tvdbId"))
        title = series_data.get("title", "Unknown Series")
        sonarr_series_id = series_data.get("id")  # Extract Sonarr series ID

        if not tvdb_id:
            logger.warning(f"No tvdbId in webhook payload: {series_data}")
            raise HTTPException(status_code=400, detail="Missing tvdbId in series data")

        # Handle SeriesDelete events
        if payload.eventType == "SeriesDelete":
            logger.info(f"Processing series deletion: {title} (TVDB: {tvdb_id}, Sonarr ID: {sonarr_series_id})")

            # Find and remove from watchlist
            watchlist_entry = db.query(WatchList).filter(WatchList.tvdb_id == tvdb_id).first()
            if watchlist_entry:
                db.delete(watchlist_entry)
                logger.info(f"Removed {title} from watchlist")
            else:
                logger.info(f"Series {title} not found in watchlist")

            # Remove all TVDB cache entries
            from app.models.tvdb_cache import TVDBCache
            tvdb_deleted = db.query(TVDBCache).filter(TVDBCache.tvdb_id == tvdb_id).delete()
            logger.info(f"Removed {tvdb_deleted} TVDB cache entries for {title}")

            # Remove all Mediathek cache entries
            from app.models.mediathek_cache import MediathekCache
            mediathek_deleted = db.query(MediathekCache).filter(MediathekCache.tvdb_id == tvdb_id).delete()
            logger.info(f"Removed {mediathek_deleted} Mediathek cache entries for {title}")

            # Remove all episode monitoring state
            from app.models.episode_monitoring_state import EpisodeMonitoringState
            monitoring_deleted = db.query(EpisodeMonitoringState).filter(
                EpisodeMonitoringState.sonarr_series_id == sonarr_series_id
            ).delete()
            logger.info(f"Removed {monitoring_deleted} episode monitoring entries for {title}")

            db.commit()

            logger.info(f"Successfully processed series deletion: {title}")
            return {
                "status": "deleted",
                "series": title,
                "tvdb_id": tvdb_id,
                "removed_from_watchlist": watchlist_entry is not None,
                "tvdb_cache_removed": tvdb_deleted,
                "mediathek_cache_removed": mediathek_deleted,
                "monitoring_state_removed": monitoring_deleted
            }

        # Handle SeriesAdd/SeriesAdded events
        logger.info(f"Processing series addition: {title} (TVDB: {tvdb_id}, Sonarr ID: {sonarr_series_id})")

        # Check if series already in watchlist
        existing_entry = db.query(WatchList).filter(WatchList.tvdb_id == tvdb_id).first()
        if existing_entry:
            logger.info(f"Series {title} already in watchlist")
            return {"status": "already_watched", "series": title, "tvdb_id": tvdb_id}

        # For now, always add to watchlist (placeholder logic)
        # TODO: Check if series has regular sources in mediatheks
        logger.info(f"Adding series {title} to watchlist")

        # Add to watchlist
        watchlist_entry = WatchList(
            tvdb_id=tvdb_id,
            show_name=title,
            sonarr_series_id=sonarr_series_id,  # Store Sonarr series ID
            import_source="webhook"
        )
        db.add(watchlist_entry)
        db.commit()

        # Start mediathek caching (will auto-fetch TVDB data if needed)
        try:
            logger.info(f"Starting mediathek caching for {title}")
            await cacher.cache_series(tvdb_id, title)
        except Exception as e:
            logger.error(f"Failed to start caching for {title}: {e}")
            # Don't fail the webhook if caching fails

        # Try to tag the series in Sonarr if webhook manager is configured
        tagging_result = None
        try:
            # Get Sonarr config
            sonarr_url_config = db.query(Config).filter_by(key="sonarr_url").first()
            sonarr_api_config = db.query(Config).filter_by(key="sonarr_api_key").first()

            if sonarr_url_config and sonarr_api_config and sonarr_url_config.value and sonarr_api_config.value:
                webhook_manager = SonarrWebhookManager(sonarr_url_config.value, sonarr_api_config.value)
                tagging_result = await webhook_manager.tag_series_in_sonarr(tvdb_id, db)
                if tagging_result and tagging_result.get("success"):
                    logger.info(f"Successfully tagged series {title} in Sonarr")
                else:
                    logger.warning(f"Failed to tag series {title} in Sonarr: {tagging_result}")
            else:
                logger.debug("Sonarr not configured, skipping tagging")
        except Exception as e:
            logger.error(f"Error during Sonarr tagging for {title}: {e}")
            # Don't fail webhook if tagging fails

        logger.info(f"Successfully processed series addition: {title}")
        return {
            "status": "processed",
            "series": title,
            "tvdb_id": tvdb_id,
            "added_to_watchlist": True,
            "caching_started": True,
            "tagged_in_sonarr": tagging_result.get("success") if tagging_result else False
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook processing error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Webhook processing failed: {str(e)}")


@router.post("/sonarr/test")
async def test_webhook():
    """
    Test endpoint for webhook functionality
    """
    logger.info("Test webhook received")
    return {"status": "test_received", "message": "Webhook test successful"}
