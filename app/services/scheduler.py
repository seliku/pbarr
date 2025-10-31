from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import logging
import asyncio

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

async def process_download_queue(db):
    """Verarbeite queued Downloads"""
    from app.models.download import Download
    from app.services.download_manager import DownloadManager
    
    manager = DownloadManager(db)
    
    # Finde alle queued Downloads
    queued_downloads = db.query(Download).filter_by(status="queued").all()
    
    if not queued_downloads:
        logger.debug("No queued downloads")
        return
    
    logger.info(f"Processing {len(queued_downloads)} queued downloads")
    
    for download in queued_downloads:
        try:
            success = await manager.download_episode(download)
            if success:
                logger.info(f"✓ Downloaded: {download.filename}")
            else:
                logger.warning(f"⚠ Failed: {download.filename}")
        except Exception as e:
            logger.error(f"✗ Error processing {download.filename}: {e}")

async def scheduled_tasks(db):
    """Regelmäßige Tasks"""
    await process_download_queue(db)

def start_scheduler(app, db):
    """Startet APScheduler"""
    from app.api.system import fetch_releases

    # Update Check (täglich 3 Uhr)
    scheduler.add_job(
        fetch_releases,
        args=[db],
        trigger=CronTrigger(hour=3, minute=0),
        id="daily_update_check",
        name="Daily Update Check"
    )

    # Download Queue (jede Minute)
    scheduler.add_job(
        scheduled_tasks,
        args=[db],
        trigger=CronTrigger(minute="*"),
        id="process_download_queue",
        name="Process Download Queue"
    )

    if not scheduler.running:
        scheduler.start()
        logger.info("✓ Scheduler started")
