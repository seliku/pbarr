import logging
import asyncio
import os
import shutil
from pathlib import Path
from datetime import datetime
from sqlalchemy.orm import Session
import subprocess

from app.models.download import Download
from app.utils.network import get_socks5_proxy_url

logger = logging.getLogger(__name__)

class DownloadManager:
    INCOMPLETE_DIR = Path("/app/downloads/incomplete")
    COMPLETED_DIR = Path("/app/downloads/completed")
    
    def __init__(self, db: Session):
        self.db = db
        self._ensure_dirs()
    
    def _ensure_dirs(self):
        """Erstelle Verzeichnisse falls nicht vorhanden"""
        for dir_path in [self.INCOMPLETE_DIR, self.COMPLETED_DIR]:
            dir_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"✓ Download directory: {dir_path}")
    
    async def queue_download(self, episode_id: str, source_url: str, filename: str) -> Download:
        """Füge Episode zur Download-Queue hinzu"""
        
        download = Download(
            episode_id=episode_id,
            source_url=source_url,
            filename=filename,
            status="queued",
            created_at=datetime.utcnow()
        )
        self.db.add(download)
        self.db.commit()
        self.db.refresh(download)
        
        logger.info(f"✓ Queued: {filename} (ID: {download.id})")
        return download
    
    async def download_episode(self, download: Download) -> bool:
        """Download Episode mit yt-dlp"""
        
        try:
            download.status = "downloading"
            download.started_at = datetime.utcnow()
            self.db.commit()
            
            logger.info(f"Downloading: {download.filename}")
            
            # Output Pfad
            output_path = self.INCOMPLETE_DIR / download.filename
            
            # yt-dlp Command
            cmd = [
                'yt-dlp',
                '-f', 'best',
                '-o', str(output_path),
                download.source_url
            ]

            # SOCKS5 Proxy Support
            proxy_url = get_socks5_proxy_url()
            if proxy_url:
                logger.info(f"Using SOCKS5 proxy for yt-dlp: {proxy_url}")
                cmd.insert(1, '--proxy')
                cmd.insert(2, proxy_url)
            else:
                logger.debug("No SOCKS5 proxy configured for yt-dlp")

            # Starte Download
            result = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                timeout=3600  # 1 Stunde max
            )
            
            if result.returncode != 0:
                raise Exception(f"yt-dlp failed: {result.stderr}")
            
            # ✅ FIX: Nutze shutil.move statt .rename() für Cross-Device
            completed_path = self.COMPLETED_DIR / download.filename
            shutil.move(str(output_path), str(completed_path))
            
            download.status = "completed"
            download.completed_at = datetime.utcnow()
            download.file_path = str(completed_path)
            download.progress = 100.0
            
            self.db.commit()
            logger.info(f"✓ Completed: {download.filename}")
            return True
            
        except Exception as e:
            logger.error(f"✗ Download failed: {e}")
            
            download.status = "failed"
            download.error_message = str(e)
            download.retries += 1
            
            if download.retries < download.max_retries:
                download.status = "queued"
                logger.info(f"Retry {download.retries}/{download.max_retries}")
            
            self.db.commit()
            return False
    
    def get_queue_status(self) -> dict:
        """Queue Status"""
        queued = self.db.query(Download).filter_by(status="queued").count()
        downloading = self.db.query(Download).filter_by(status="downloading").count()
        completed = self.db.query(Download).filter_by(status="completed").count()
        failed = self.db.query(Download).filter_by(status="failed").count()
        
        return {
            "queued": queued,
            "downloading": downloading,
            "completed": completed,
            "failed": failed,
            "total": queued + downloading + completed + failed
        }
