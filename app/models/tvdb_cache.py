from sqlalchemy import Column, Integer, String, DateTime, Text, Date, UniqueConstraint
from datetime import datetime
from app.database import Base


class TVDBCache(Base):
    __tablename__ = "tvdb_cache"
    
    id = Column(Integer, primary_key=True)
    
    # Show Info
    tvdb_id = Column(String(50), nullable=False, index=True)
    show_name = Column(String(255))
    
    # Episode Info
    season = Column(Integer, nullable=False)
    episode = Column(Integer, nullable=False)
    episode_name = Column(String(500), nullable=False)
    description = Column(Text)
    
    # Air Date
    aired_date = Column(Date, nullable=True, index=True)
    
    # Metadata
    cached_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint('tvdb_id', 'season', 'episode', name='uq_tvdb_episode'),
    )
