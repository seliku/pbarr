from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
import os


# ✅ Setup Logging FIRST
from app.utils.logger import setup_logging
setup_logging(log_level=os.getenv("LOG_LEVEL", "INFO"))


# Services
from app.database import init_db, get_db
from app.services.download_worker import DownloadWorker
from app.services.mediathek_cacher import cacher
from app.startup import init_config, load_enabled_modules


# API Routes
from app.api import admin, search, system, downloads, matcher, matcher_admin, integration


logger = logging.getLogger(__name__)

# Worker wird hier erstellt, nicht global
download_worker = None
scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global download_worker, scheduler
    
    # Startup
    logger.info("Starting PBArr...")
    try:
        init_db()
        logger.info("✓ Database initialized")
    except Exception as e:
        logger.error(f"✗ Database init failed: {e}")

    try:
        init_config()
    except Exception as e:
        logger.error(f"✗ Config init failed: {e}")

    try:
        download_worker = DownloadWorker(interval=30)
        download_worker.start()
    except Exception as e:
        logger.error(f"✗ Download worker init failed: {e}")

    # Start Scheduler für Cache Jobs
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger
        
        scheduler = AsyncIOScheduler()
        
        # Hourly: Cache Sync
        scheduler.add_job(
            cacher.sync_watched_shows,
            'interval',
            hours=1,
            id='mediathek_sync',
            name='Mediathek Cache Sync (Hourly)'
        )
        
        # Daily: Cleanup
        scheduler.add_job(
            cacher.cleanup_expired,
            'cron',
            hour=2,
            minute=0,
            id='cache_cleanup_expired',
            name='Cleanup Expired Cache'
        )
        
        scheduler.add_job(
            cacher.cleanup_unwatched,
            'cron',
            hour=3,
            minute=0,
            id='cache_cleanup_unwatched',
            name='Cleanup Unwatched Shows'
        )
        
        scheduler.start()
        logger.info("✓ Scheduler started (hourly cache, daily cleanup)")
    except Exception as e:
        logger.error(f"✗ Scheduler init failed: {e}")

    yield

    # Shutdown
    logger.info("Shutting down PBArr...")
    if download_worker:
        download_worker.stop()
    if scheduler and scheduler.running:
        scheduler.shutdown()


app = FastAPI(
    title="PBArr - Public Broadcasting Archive Indexer",
    description="Newznab API für deutschsprachige Mediatheken",
    version="0.1.0",
    lifespan=lifespan
)


# Routes
app.include_router(admin.router)
app.include_router(search.router)
app.include_router(system.router)
app.include_router(downloads.router)
app.include_router(matcher.router)
app.include_router(matcher_admin.router)
app.include_router(integration.router)


# Static Files (Optional)
try:
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
except Exception as e:
    logger.warning(f"Static files not available: {e}")


@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/")
async def root():
    return JSONResponse({
        "app": "PBArr",
        "version": "0.1.0",
        "docs": "/docs",
        "admin": "/admin",
        "health": "/health"
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
