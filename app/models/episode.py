from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey
from datetime import datetime
from app.database import Base

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
    
    source_url = Column(String, nullable=True)
    source = Column(String)
    
    media_url = Column(String, nullable=True)
    file_path = Column(String, nullable=True)
    
    quality = Column(String, default="1080p")
    language = Column(String, default="de")
    
    indexed_at = Column(DateTime, default=datetime.utcnow)
    is_available = Column(Boolean, default=True)
    
    def __repr__(self):
        return f"<Episode S{self.season:02d}E{self.episode_number:02d}: {self.title}>"
