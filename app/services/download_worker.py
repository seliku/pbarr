import logging
import asyncio
import threading
import time
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.download import Download
from app.services.download_manager import DownloadManager
from app.database import SessionLocal

logger = logging.getLogger(__name__)

class DownloadWorker:
    def __init__(self, interval: int = 10):
        """
        interval: Sekunden zwischen Download-Queue Checks
        """
        self.interval = interval
        self.running = False
        self.thread = None
    
    def start(self):
        """Starte Worker Thread"""
        if self.running:
            logger.warning("Worker already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.thread.start()
        logger.info(f"✓ Download Worker started (interval: {self.interval}s)")
    
    def stop(self):
        """Stoppe Worker"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Download Worker stopped")
    
    def _worker_loop(self):
        """Main Worker Loop"""
        while self.running:
            try:
                db = SessionLocal()
                self._process_queue(db)
                db.close()
            except Exception as e:
                logger.error(f"Worker error: {e}")
            
            # Warte auf nächste Iteration
            for _ in range(self.interval):
                if not self.running:
                    break
                time.sleep(1)
    
    def _process_queue(self, db: Session):
        """Verarbeite Download-Queue"""
        
        # Finde queued Downloads
        queued = db.query(Download).filter_by(status="queued").all()
        
        if not queued:
            return
        
        logger.info(f"Processing {len(queued)} queued downloads")
        
        for download in queued:
            if not self.running:
                break
            
            try:
                # Synchroner Call zu async download_episode
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                manager = DownloadManager(db)
                success = loop.run_until_complete(
                    manager.download_episode(download)
                )
                
                loop.close()
                
                if success:
                    logger.info(f"✓ Downloaded: {download.filename}")
                else:
                    logger.warning(f"⚠ Failed: {download.filename}")
            
            except Exception as e:
                logger.error(f"✗ Error: {download.filename} - {e}")


# WICHTIG: Keine Global Instance! Wird in main.py erstellt
