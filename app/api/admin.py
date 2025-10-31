from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import os
import logging


from app.database import get_db
from app.models.config import Config
from app.models.module_state import ModuleState


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/admin", tags=["admin"])


# Pydantic Schemas
class ConfigCreate(BaseModel):
    key: str
    value: str
    module: str = "core"
    secret: bool = False
    data_type: str = "string"
    description: Optional[str] = None


class ConfigUpdate(BaseModel):
    value: str


class ConfigResponse(BaseModel):
    id: int
    key: str
    value: str
    module: str
    secret: bool
    data_type: str
    description: Optional[str]
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ModuleResponse(BaseModel):
    id: int
    module_name: str
    module_type: str
    enabled: bool
    version: str
    last_updated: datetime
    
    class Config:
        from_attributes = True


# HTML Admin Panel
@router.get("/")
async def admin_panel():
    """Serve admin.html"""
    admin_html = os.path.join(os.path.dirname(__file__), "..", "static", "admin.html")
    if os.path.exists(admin_html):
        return FileResponse(admin_html, media_type="text/html")
    return {"error": "Admin panel not found"}


# Endpoints
@router.get("/config", response_model=List[ConfigResponse])
async def get_all_config(db: Session = Depends(get_db)):
    """Alle Konfigurationen abrufen"""
    configs = db.query(Config).order_by(Config.module, Config.key).all()
    return configs


@router.get("/config/{key}", response_model=ConfigResponse)
async def get_config(key: str, db: Session = Depends(get_db)):
    """Einzelne Konfiguration abrufen"""
    config = db.query(Config).filter(Config.key == key).first()
    if not config:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")
    return config


@router.post("/config", response_model=ConfigResponse)
async def create_config(config: ConfigCreate, db: Session = Depends(get_db)):
    """Neue Konfiguration erstellen"""
    existing = db.query(Config).filter(Config.key == config.key).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Config key '{config.key}' already exists")
    
    new_config = Config(**config.dict())
    db.add(new_config)
    db.commit()
    db.refresh(new_config)
    return new_config


@router.put("/config/{key}", response_model=ConfigResponse)
async def update_config(key: str, update: ConfigUpdate, db: Session = Depends(get_db)):
    """Konfiguration aktualisieren (Value only)"""
    config = db.query(Config).filter(Config.key == key).first()
    if not config:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")
    
    config.value = update.value
    config.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(config)
    return config


@router.delete("/config/{key}")
async def delete_config(key: str, db: Session = Depends(get_db)):
    """Konfiguration löschen"""
    config = db.query(Config).filter(Config.key == key).first()
    if not config:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")
    
    db.delete(config)
    db.commit()
    return {"message": f"Config key '{key}' deleted"}


# Module Management
@router.get("/modules", response_model=List[ModuleResponse])
async def get_modules(db: Session = Depends(get_db)):
    """Alle Module abrufen"""
    modules = db.query(ModuleState).all()
    return modules


@router.put("/modules/{module_name}/toggle")
async def toggle_module(module_name: str, enabled: bool, db: Session = Depends(get_db)):
    """Modul aktivieren/deaktivieren"""
    module = db.query(ModuleState).filter(ModuleState.module_name == module_name).first()
    if not module:
        raise HTTPException(status_code=404, detail=f"Module '{module_name}' not found")
    
    module.enabled = enabled
    db.commit()
    db.refresh(module)
    
    status = "✓ enabled" if enabled else "✗ disabled"
    return {"module": module_name, "status": status}


# Dashboard Overview
@router.get("/dashboard")
async def get_dashboard(db: Session = Depends(get_db)):
    """Dashboard-Übersicht"""
    config_count = db.query(Config).count()
    modules_enabled = db.query(ModuleState).filter(ModuleState.enabled == True).count()
    modules_total = db.query(ModuleState).count()
    
    return {
        "config_items": config_count,
        "modules": {
            "enabled": modules_enabled,
            "total": modules_total
        }
    }


# Cache Management
@router.post("/trigger-cache-sync")
async def trigger_cache_sync(db: Session = Depends(get_db)):
    """Manually trigger Mediathek cache sync"""
    try:
        from app.services.mediathek_cacher import cacher
        
        logger.info("🔄 Manual cache sync triggered")
        await cacher.sync_watched_shows()
        
        return {"success": True, "message": "Cache sync completed"}
    except Exception as e:
        logger.error(f"❌ Cache sync error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync-tvdb")
async def sync_tvdb(tvdb_id: str = Query(...), db: Session = Depends(get_db)):
    """Manually sync TVDB episodes for a show"""
    try:
        from app.services.tvdb_client import TVDBClient
        
        tvdb_key_config = db.query(Config).filter_by(key="tvdb_api_key").first()
        if not tvdb_key_config or not tvdb_key_config.value:
            raise HTTPException(status_code=400, detail="TVDB API key not configured")
        
        logger.info(f"🔄 Syncing TVDB for {tvdb_id}")
        
        tvdb_client = TVDBClient(tvdb_key_config.value, db=db)
        episodes = await tvdb_client.get_episodes(tvdb_id)
        
        return {"success": True, "episodes": len(episodes), "message": f"Synced {len(episodes)} episodes"}
    
    except Exception as e:
        logger.error(f"TVDB sync error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
