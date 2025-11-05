from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import logging
import asyncio

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

async def scheduled_tasks(db):
    """Regelmäßige Tasks"""
    # Keine Download-Queue mehr - alles läuft über curl
    pass

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

    # Keine Download-Queue mehr - alles läuft über curl

    if not scheduler.running:
        scheduler.start()
        logger.info("✓ Scheduler started")
