import aiohttp
import json
from datetime import datetime
from packaging import version
from sqlalchemy.orm import Session
from app.models.version import AppVersion, UpdateCheck

class UpdateChecker:
    GITHUB_API = "https://api.github.com/repos/YOUR_USERNAME/pbarr/releases"
    from app import __version__ as CURRENT_VERSION
    
    def __init__(self, db: Session):
        self.db = db
    
    async def check_for_updates(self) -> dict:
        """Prüft GitHub auf neue Releases"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.GITHUB_API, timeout=10) as resp:
                    if resp.status == 200:
                        releases = await resp.json()
                        return self._parse_releases(releases)
        except Exception as e:
            print(f"Update check failed: {e}")
        return {}
    
    def _parse_releases(self, releases: list) -> dict:
        """Parst GitHub Releases in Versionen"""
        latest = None
        
        for release in releases:
            if release.get("draft"):
                continue
            
            tag = release["tag_name"].lstrip("v")
            app_version = AppVersion(
                version=tag,
                changelog=release.get("body", ""),
                is_stable=not release.get("prerelease", False)
            )
            
            # Erste nicht-Draft ist latest
            if latest is None and app_version.is_stable:
                latest = tag
            
            # In DB speichern (wenn nicht existiert)
            existing = self.db.query(AppVersion).filter_by(version=tag).first()
            if not existing:
                self.db.add(app_version)
        
        self.db.commit()
        
        # Update-Status aktualisieren
        return self._update_check_status(latest)
    
    def _update_check_status(self, latest_available: str) -> dict:
        """Aktualisiert UpdateCheck Tabelle"""
        update_check = self.db.query(UpdateCheck).first()
        if not update_check:
            update_check = UpdateCheck()
            self.db.add(update_check)
        
        update_check.last_check = datetime.utcnow()
        update_check.latest_available = latest_available
        update_check.current_installed = self.CURRENT_VERSION
        update_check.update_available = (
            version.parse(latest_available) > version.parse(self.CURRENT_VERSION)
            if latest_available else False
        )
        
        self.db.commit()
        
        return {
            "current": self.CURRENT_VERSION,
            "latest": latest_available,
            "update_available": update_check.update_available,
            "last_check": update_check.last_check.isoformat()
        }
