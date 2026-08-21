from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
import os


# ✅ Setup Logging FIRST
from app.utils.logger import setup_logging
from app.database import SessionLocal
from app.models.config import Config
from app import __version__


# Setup basic logging first (before DB access)
setup_logging("INFO")  # Default level

def get_log_level_from_db():
    """Lese Log-Level aus Datenbank, mit Fallback"""
    try:
        db = SessionLocal()
        config = db.query(Config).filter_by(key="log_level").first()
        db.close()
        if config:
            return config.value.upper()
    except Exception as e:
        logging.warning(f"Could not read log_level from DB: {e}")

    # Fallback auf Default
    return "INFO"

# Reduziere Spam von externen Libraries
logging.getLogger('apscheduler').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)




# Services
from app.database import init_db, get_db
from app.services.mediathek_direct import direct
from app.startup import init_config, load_enabled_modules, init_download_directory, run_migrations


# API Routes
from app.api import admin, system


logger = logging.getLogger(__name__)

# Scheduler
scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler

    # Startup
    logger.info("Starting PBArr...")
    try:
        init_db()
        logger.info("✓ Database initialized")
    except Exception as e:
        logger.error(f"✗ Database init failed: {e}")
        # Don't continue if database init fails
        raise

    try:
        run_migrations()
    except Exception as e:
        logger.error(f"✗ Migration check failed: {e}")
        # Continue anyway - app should still work

    try:
        init_config()
    except Exception as e:
        logger.error(f"✗ Config init failed: {e}")
        # Continue anyway - config might be created later



    try:
        init_download_directory()
    except Exception as e:
        logger.error(f"✗ Download directory init failed: {e}")

    # Quellen einmal beim Start laden.
    #
    # Der Lader wuerde das auch bei der ersten Suche tun, aber dann faellt ein
    # defektes Modul erst Stunden spaeter auf. Wer eine Quelle schreibt, soll
    # beim Neustart sofort sehen, ob sie gefunden wurde.
    try:
        from app.modules.sources.registry import discover_sources
        sources = discover_sources(refresh=True)
        logger.info(f"✓ {len(sources)} Quelle(n) verfuegbar: {', '.join(sources)}")
    except Exception as e:
        logger.error(f"✗ Quellen konnten nicht geladen werden: {e}")

    # Start Scheduler für Cache Jobs
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger
        
        scheduler = AsyncIOScheduler()
        
        # Stuendlich: direkter Mediathek-Abgleich.
        #
        # Loest den alten Weg ab, der Sonarr und TVDB brauchte und deshalb
        # nie etwas heruntergeladen hat - beide Nummerierungen liefen
        # auseinander. Siehe mediathek_direct.py.
        scheduler.add_job(
            direct.sync_watchlist,
            'interval',
            hours=1,
            id='mediathek_sync',
            name='Mediathek Sync (stuendlich)'
        )
        
        # Cache-Aufraeumen entfaellt - der direkte Weg nutzt keinen Cache.
        
        # cleanup_unwatched wurde aus dem Zeitplan genommen.
        #
        # Sie loeschte Watch-List-Eintraege nach 30 Tagen ohne Aktualisierung -
        # zusammen mit dem Sonarr-Fehler war das der Grund, warum Serien immer
        # wieder verschwanden. Der Cache-Ablauf (cleanup_expired) laeuft weiter.
        
        scheduler.start()
        logger.info("✓ Scheduler started (hourly cache, daily cleanup)")
    except Exception as e:
        logger.error(f"✗ Scheduler init failed: {e}")

    yield

    # Shutdown
    logger.info("Shutting down PBArr...")
    if scheduler and scheduler.running:
        scheduler.shutdown()


app = FastAPI(
    title="PBArr - Public Broadcasting Archive Indexer",
    description="Mediathek-Caching und Verwaltung für deutschsprachige Mediatheken",
    version=__version__,
    lifespan=lifespan
)


# Routes
# Sonarr-Webhook und TVDB-Matcher sind nicht mehr eingebunden.
#
# Der Abgleich laeuft direkt gegen die Mediathek: Name rein, Sendung raus.
# Die Module liegen noch im Baum, bis die Beta sich bewaehrt hat.
app.include_router(admin.router)
app.include_router(system.router)




# Static Files (Optional)
try:
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
except Exception as e:
    logger.warning(f"Static files not available: {e}")


@app.get("/health")
async def health_check():
    return {"status": "ok", "version": __version__}


@app.get("/")
async def root():
    return JSONResponse({
        "app": "PBArr",
        "version": __version__,
        "docs": "/docs",
        "admin": "/admin",
        "health": "/health"
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
