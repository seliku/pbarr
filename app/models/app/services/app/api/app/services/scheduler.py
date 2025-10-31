from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.update_checker import UpdateChecker

scheduler = AsyncIOScheduler()

async def scheduled_update_check(db_session):
    """Täglich um 3 Uhr nachts prüfen"""
    checker = UpdateChecker(db_session)
    await checker.check_for_updates()

def start_scheduler(app, db):
    scheduler.add_job(
        scheduled_update_check,
        "cron",
        hour=3,
        minute=0,
        args=[db],
        id="daily_update_check"
    )
    scheduler.start()
