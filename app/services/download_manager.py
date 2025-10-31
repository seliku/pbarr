"""
Download Queue Manager - verwaltet yt-dlp Downloads
"""
import asyncio
import logging
import subprocess
import json
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.download import Download
from app.database import SessionLocal

logger = logging.getLogger(__name__)

class DownloadManager:
    def __init__(self, db: Session):
        self.db = db
        self.max_concurrent = 2
        self.active_downloads = {}
    
    async def queue_download(self, episode_id: str, source_url: str, filename: str) -> Download:
        """Episode zur Download-Queue hinzufügen"""
        download = Download(
            episode_id=episode_id,
            source_url=source_url,
            filename=filename,
            status="queued"
        )
        self.db.add(download)
        self.db.commit()
        self.db.refresh(download)
        logger.info(f"Queued download: {filename}")
        return download
    
    async def start_download(self, download_id: int) -> bool:
        """Startet Download mit yt-dlp"""
        download = self.db.query(Download).filter_by(id=download_id).first()
        if not download:
            return False
        
        try:
            download.status = "downloading"
            download.started_at = datetime.utcnow()
            self.db.commit()
            
            # yt-dlp command
            cmd = [
                'yt-dlp',
                '-f', 'best',
                '-o', download.file_path or f'/app/downloads/{download.filename}.%(ext)s',
                download.source_url
            ]
            
            logger.info(f"Starting download: {download.filename}")
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            self.active_downloads[download_id] = process
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                download.status = "completed"
                download.completed_at = datetime.utcnow()
                download.progress = 100.0
                logger.info(f"✓ Download completed: {download.filename}")
            else:
                download.status = "failed"
                download.error_message = stderr.decode() if stderr else "Unknown error"
                download.retries += 1
                
                if download.retries < download.max_retries:
                    download.status = "queued"
                    logger.warning(f"Download failed, retrying... ({download.retries}/{download.max_retries})")
                else:
                    logger.error(f"✗ Download failed: {download.filename}")
            
            self.db.commit()
            self.active_downloads.pop(download_id, None)
            return process.returncode == 0
        
        except Exception as e:
            download.status = "failed"
            download.error_message = str(e)
            self.db.commit()
            logger.error(f"Download error: {e}")
            return False
    
    async def process_queue(self):
        """Background task - verarbeitet Download Queue"""
        while True:
            try:
                # Finde queued Downloads
                queued = self.db.query(Download).filter_by(status="queued").limit(self.max_concurrent).all()
                
                for download in queued:
                    if len(self.active_downloads) < self.max_concurrent:
                        await self.start_download(download.id)
                
                await asyncio.sleep(10)
            
            except Exception as e:
                logger.error(f"Download queue error: {e}")
                await asyncio.sleep(10)
    
    def get_queue_status(self) -> dict:
        """Gibt Status der Download Queue"""
        queued = self.db.query(Download).filter_by(status="queued").count()
        active = self.db.query(Download).filter_by(status="downloading").count()
        completed = self.db.query(Download).filter_by(status="completed").count()
        failed = self.db.query(Download).filter_by(status="failed").count()
        
        return {
            "queued": queued,
            "active": active,
            "completed": completed,
            "failed": failed,
            "total": queued + active + completed + failed
        }
