from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, Float
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class Download(Base):
    __tablename__ = "downloads"
    
    id = Column(Integer, primary_key=True)
    episode_id = Column(String, nullable=False)  # Referenz zu Episode
    
    status = Column(String, default="queued")  # queued, downloading, completed, failed
    
    source_url = Column(String, nullable=False)
    file_path = Column(String, nullable=True)
    filename = Column(String, nullable=True)
    
    progress = Column(Float, default=0.0)  # 0-100%
    error_message = Column(Text, nullable=True)
    
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    retries = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    
    def __repr__(self):
        return f"<Download {self.filename} [{self.status}]>"
