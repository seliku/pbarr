from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

from app.database import get_db
from app.models.config import Config
from app.models.module_state import ModuleState

router = APIRouter(prefix="/admin", tags=["admin"])

# Pydantic Schemas
class ConfigCreate(BaseModel):
    key: str
    value: str
    module: str = "core"
    secret: bool = False
    data_type: str = "string"
    description: Optional[str] = None

class ConfigResponse(BaseModel):
    id: int
    key: str
    value: str
    module: str
    secret: bool
    data_type: str
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

# Endpoints
@router.get("/config", response_model=List[ConfigResponse])
async def get_all_config(db: Session = Depends(get_db)):
    """Alle Konfigurationen abrufen"""
    configs = db.query(Config).all()
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
async def update_config(key: str, config: ConfigCreate, db: Session = Depends(get_db)):
    """Konfiguration aktualisieren"""
    existing = db.query(Config).filter(Config.key == key).first()
    if not existing:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")
    
    for field, value in config.dict().items():
        setattr(existing, field, value)
    
    db.commit()
    db.refresh(existing)
    return existing

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
