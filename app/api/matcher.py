from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.models.config import Config

router = APIRouter(prefix="/api/matcher", tags=["matcher"])

class MatchShowRequest(BaseModel):
    title: str
    year: Optional[int] = None

@router.post("/match-show")
async def match_show(request: MatchShowRequest, db: Session = Depends(get_db)):
    """
    Placeholder für Show-Matching
    Wird durch pattern_matcher ersetzt
    """
    return {
        "message": "Use /api/matcher-admin for pattern configuration"
    }

@router.post("/match-episode")
async def match_episode(
    tvdb_show_id: str,
    season: int,
    episode: int,
    db: Session = Depends(get_db)
):
    """
    Placeholder für Episode-Matching
    """
    return {
        "message": "Use /api/matcher-admin for pattern configuration"
    }
