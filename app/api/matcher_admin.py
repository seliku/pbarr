from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

from app.database import get_db
from app.models.matcher_config import MatcherConfig
from app.services.pattern_matcher import PatternMatcher, MatcherTemplates

router = APIRouter(prefix="/api/matcher-admin", tags=["matcher-admin"])

class MatcherConfigCreate(BaseModel):
    name: str
    source: str
    strategy: str = "regex"
    title_pattern: Optional[str]
    season_pattern: Optional[str]
    episode_pattern: Optional[str]
    title_group: int = 1
    season_group: int = 1
    episode_group: int = 1
    default_season: int = 1
    test_string: Optional[str]

class MatcherConfigResponse(BaseModel):
    id: int
    name: str
    source: str
    strategy: str
    title_pattern: Optional[str]
    season_pattern: Optional[str]
    episode_pattern: Optional[str]
    title_group: int
    season_group: int
    episode_group: int
    default_season: int
    enabled: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

@router.get("/configs", response_model=List[MatcherConfigResponse])
async def list_configs(source: Optional[str] = None, db: Session = Depends(get_db)):
    """Alle Matcher Configs auflisten"""
    query = db.query(MatcherConfig)
    if source:
        query = query.filter_by(source=source)
    return query.all()

@router.get("/configs/{config_id}", response_model=MatcherConfigResponse)
async def get_config(config_id: int, db: Session = Depends(get_db)):
    """Einzelne Matcher Config abrufen"""
    config = db.query(MatcherConfig).filter_by(id=config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    return config

@router.post("/configs", response_model=MatcherConfigResponse)
async def create_config(config: MatcherConfigCreate, db: Session = Depends(get_db)):
    """Neue Matcher Config erstellen"""
    existing = db.query(MatcherConfig).filter_by(name=config.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Config already exists")
    
    new_config = MatcherConfig(**config.dict())
    db.add(new_config)
    db.commit()
    db.refresh(new_config)
    return new_config

@router.put("/configs/{config_id}", response_model=MatcherConfigResponse)
async def update_config(config_id: int, config: MatcherConfigCreate, db: Session = Depends(get_db)):
    """Matcher Config aktualisieren"""
    existing = db.query(MatcherConfig).filter_by(id=config_id).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Config not found")
    
    for field, value in config.dict().items():
        setattr(existing, field, value)
    
    existing.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(existing)
    return existing

@router.delete("/configs/{config_id}")
async def delete_config(config_id: int, db: Session = Depends(get_db)):
    """Matcher Config löschen"""
    config = db.query(MatcherConfig).filter_by(id=config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    
    db.delete(config)
    db.commit()
    return {"message": "Config deleted"}

@router.post("/test/{config_id}")
async def test_matcher(config_id: int, test_string: str, db: Session = Depends(get_db)):
    """Test Matcher gegen String"""
    config = db.query(MatcherConfig).filter_by(id=config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    
    matcher = PatternMatcher(config)
    result = matcher.test(test_string)
    return result

@router.get("/templates")
async def list_templates():
    """Vordefinierte Matcher-Templates"""
    return {
        "ard_simple": {
            "name": "ARD Simple (Folge X)",
            "template": MatcherTemplates.ARD_SIMPLE,
            "example": "Die Sendung mit der Maus - Folge 42"
        },
        "zdf_standard": {
            "name": "ZDF Standard (SxxExx)",
            "template": MatcherTemplates.ZDF_STANDARD,
            "example": "Das Duell S2E3 - Der Titel"
        },
        "generic_standard": {
            "name": "Generic Standard (SxxExx)",
            "template": MatcherTemplates.GENERIC_STANDARD,
            "example": "Show Title S01E05"
        }
    }

@router.post("/apply-template")
async def apply_template(template_name: str, name: str, source: str, db: Session = Depends(get_db)):
    """Wende vordefiniertes Template an"""
    templates = {
        "ard_simple": MatcherTemplates.ARD_SIMPLE,
        "zdf_standard": MatcherTemplates.ZDF_STANDARD,
        "generic_standard": MatcherTemplates.GENERIC_STANDARD,
    }
    
    if template_name not in templates:
        raise HTTPException(status_code=404, detail="Template not found")
    
    template = templates[template_name]
    
    new_config = MatcherConfig(
        name=name,
        source=source,
        **template
    )
    db.add(new_config)
    db.commit()
    db.refresh(new_config)
    
    return {
        "id": new_config.id,
        "name": new_config.name,
        "message": f"Template '{template_name}' applied"
    }
