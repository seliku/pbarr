from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from datetime import datetime
import aiohttp
from packaging import version

from app.database import get_db
from app.models import AppVersion, UpdateCheck, Config

router = APIRouter(prefix="/api/system", tags=["system"])

CURRENT_VERSION = "0.1.0"
GITHUB_REPO = "YOUR_USERNAME/pbarr"  # Später via Config
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases"

@router.get("/version")
async def get_version(db: Session = Depends(get_db)):
    """Aktuelle Version"""
    check = db.query(UpdateCheck).first()
    if not check:
        check = UpdateCheck(current_installed=CURRENT_VERSION)
        db.add(check)
        db.commit()
    
    return {
        "version": CURRENT_VERSION,
        "last_update_check": check.last_check.isoformat() if check else None,
        "latest_available": check.latest_available if check else None
    }

@router.post("/check-updates")
async def check_updates(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Manuell Updates prüfen"""
    background_tasks.add_task(fetch_releases, db)
    return {"status": "Update check started in background"}

@router.get("/update-status")
async def get_update_status(db: Session = Depends(get_db)):
    """Status des letzten Update-Checks"""
    check = db.query(UpdateCheck).first()
    if not check:
        return {"status": "never_checked"}
    
    return {
        "current": check.current_installed,
        "latest": check.latest_available,
        "update_available": check.update_available,
        "last_check": check.last_check.isoformat(),
        "auto_update_enabled": check.auto_update_enabled
    }

async def fetch_releases(db: Session):
    """Fetched GitHub Releases (Background Task)"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(GITHUB_API, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    releases = await resp.json()
                    
                    latest_stable = None
                    for release in releases:
                        if release.get("draft"):
                            continue
                        
                        tag = release["tag_name"].lstrip("v")
                        app_version = AppVersion(
                            version=tag,
                            changelog=release.get("body", ""),
                            is_stable=not release.get("prerelease", False)
                        )
                        
                        if latest_stable is None and app_version.is_stable:
                            latest_stable = tag
                        
                        # Nur neue Versionen speichern
                        existing = db.query(AppVersion).filter_by(version=tag).first()
                        if not existing:
                            db.add(app_version)
                    
                    db.commit()
                    
                    # UpdateCheck aktualisieren
                    update_check = db.query(UpdateCheck).first()
                    if not update_check:
                        update_check = UpdateCheck()
                        db.add(update_check)
                    
                    update_check.last_check = datetime.utcnow()
                    update_check.latest_available = latest_stable
                    update_check.current_installed = CURRENT_VERSION
                    update_check.update_available = (
                        version.parse(latest_stable) > version.parse(CURRENT_VERSION)
                        if latest_stable else False
                    )
                    
                    db.commit()
    except Exception as e:
        print(f"Update check failed: {e}")

@router.get("/versions")
async def get_all_versions(db: Session = Depends(get_db)):
    """Alle bekannten Versionen"""
    versions = db.query(AppVersion).order_by(AppVersion.version.desc()).all()
    return {
        "current": CURRENT_VERSION,
        "versions": [
            {
                "version": v.version,
                "stable": v.is_stable,
                "release_date": v.release_date.isoformat() if v.release_date else None,
                "installed": v.is_installed
            }
            for v in versions
        ]
    }
