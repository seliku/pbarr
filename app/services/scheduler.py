from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import logging

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

async def scheduled_tasks(app, db):
    """Regelmäßige Tasks"""
    pass

def start_scheduler(app, db):
    """Startet APScheduler"""
    from app.api.system import fetch_releases
    
    scheduler.add_job(
        fetch_releases,
        args=[db],
        trigger=CronTrigger(hour=3, minute=0),  # 3 Uhr nachts täglich
        id="daily_update_check",
        name="Daily Update Check"
    )
    
    if not scheduler.running:
        scheduler.start()
        logger.info("✓ Scheduler started")
