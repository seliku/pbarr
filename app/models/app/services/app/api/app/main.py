from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import logging
import os
from contextlib import asynccontextmanager

# Services
from app.database import init_db, get_db
from app.services.scheduler import start_scheduler

# API Routes
from app.api import admin, search, system

# Logging
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting PBArr...")
    init_db()
    db = next(get_db())
    start_scheduler(app, db)
    logger.info("✓ Database initialized")
    logger.info("✓ Scheduler started")
    
    yield
    
    # Shutdown
    logger.info("Shutting down PBArr...")

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

# Static Files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

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
