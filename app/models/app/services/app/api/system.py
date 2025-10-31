from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.update_checker import UpdateChecker

router = APIRouter(prefix="/api/system", tags=["system"])

@router.get("/version")
async def get_version(db: Session = Depends(get_db)):
    """Aktuelle installierte Version"""
    return {"version": "0.1.0"}

@router.post("/check-updates")
async def check_updates(db: Session = Depends(get_db)):
    """Manuell Updates prüfen"""
    checker = UpdateChecker(db)
    result = await checker.check_for_updates()
    return result

@router.get("/update-status")
async def get_update_status(db: Session = Depends(get_db)):
    """Status des letzten Update-Checks"""
    from app.models.version import UpdateCheck
    check = db.query(UpdateCheck).first()
    if not check:
        return {"status": "never_checked"}
    return {
        "current": check.current_installed,
        "latest": check.latest_available,
        "update_available": check.update_available,
        "last_check": check.last_check.isoformat()
    }
