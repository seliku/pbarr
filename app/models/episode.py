from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class Episode(Base):
    __tablename__ = "episodes"
    
    id = Column(Integer, primary_key=True)
    tvdb_id = Column(String, nullable=True)
    show_id = Column(String, ForeignKey("shows.tvdb_id"), nullable=False)
    
    season = Column(Integer, nullable=False)
    episode_number = Column(Integer, nullable=False)
    
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    air_date = Column(DateTime, nullable=True)
    
    source_url = Column(String, nullable=True)  # Mediathek URL
    source = Column(String)  # "ard", "zdf", "3sat"
    
    media_url = Column(String, nullable=True)  # Nach Download gespeichert
    file_path = Column(String, nullable=True)  # Lokales Pfad
    
    quality = Column(String, default="1080p")
    language = Column(String, default="de")
    
    indexed_at = Column(DateTime, default=datetime.utcnow)
    is_available = Column(Boolean, default=True)
    
    def __repr__(self):
        return f"<Episode S{self.season:02d}E{self.episode_number:02d}: {self.title}>"
