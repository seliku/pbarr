from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import logging
import tempfile
from datetime import datetime


from app.database import get_db
from app.models.mediathek_cache import MediathekCache
from app.models.tvdb_cache import TVDBCache


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/integration", tags=["integration"])


@router.get("/getnzb")
async def get_nzb(
    id: str = Query(...),
    db: Session = Depends(get_db)
):
    """
    Sonarr Download-Endpoint (On-Demand via Cache) - DISABLED

    Downloads are no longer supported. Episodes are downloaded directly to Sonarr library.
    """
    raise HTTPException(status_code=501, detail="Download functionality has been removed. Episodes are downloaded directly to Sonarr library.")


@router.get("/download-status")
async def download_status(download_id: int = Query(...), db: Session = Depends(get_db)):
    """Sonarr fragt Download-Status ab - DISABLED"""
    return {"status": "unknown", "message": "Download functionality has been removed"}
