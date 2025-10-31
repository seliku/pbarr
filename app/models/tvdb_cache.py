from sqlalchemy import Column, Integer, String, DateTime, Text
from datetime import datetime
from app.database import Base

class TVDBCache(Base):
    __tablename__ = "tvdb_cache"
    
    id = Column(Integer, primary_key=True)
    tvdb_id = Column(Integer, nullable=False, index=True)
    season = Column(Integer, nullable=False)
    episode = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    overview = Column(Text)
    aired = Column(String)
    cached_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        # Unique: tvdb_id + season + episode
        {},
    )
