from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List
from datetime import datetime

from app.database import get_db
from app.models.download import Download
from app.services.download_manager import DownloadManager

router = APIRouter(prefix="/api/downloads", tags=["downloads"])

class DownloadCreate(BaseModel):
    episode_id: str
    source_url: str
    filename: str

class DownloadResponse(BaseModel):
    id: int
    episode_id: str
    status: str
    filename: str
    progress: float
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    
    class Config:
        from_attributes = True

@router.get("/status")
async def get_queue_status(db: Session = Depends(get_db)):
    """Download Queue Status"""
    manager = DownloadManager(db)
    return manager.get_queue_status()

@router.post("/queue", response_model=dict)
async def queue_download(download: DownloadCreate, db: Session = Depends(get_db)):
    """Episode zur Download-Queue hinzufügen"""
    manager = DownloadManager(db)
    result = await manager.queue_download(
        download.episode_id,
        download.source_url,
        download.filename
    )
    return {
        "id": result.id,
        "status": result.status,
        "filename": result.filename
    }

@router.get("/downloads", response_model=List[DownloadResponse])
async def list_downloads(status: str = None, db: Session = Depends(get_db)):
    """Alle Downloads auflisten"""
    query = db.query(Download)
    if status:
        query = query.filter_by(status=status)
    return query.order_by(Download.created_at.desc()).limit(100).all()

@router.get("/downloads/{download_id}", response_model=DownloadResponse)
async def get_download(download_id: int, db: Session = Depends(get_db)):
    """Download Details"""
    download = db.query(Download).filter_by(id=download_id).first()
    if not download:
        raise HTTPException(status_code=404, detail="Download not found")
    return download
