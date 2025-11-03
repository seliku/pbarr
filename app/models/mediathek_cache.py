from sqlalchemy import Column, Integer, String, DateTime, Text, Index, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class MediathekCache(Base):
    __tablename__ = "mediathek_cache"
    
    id = Column(Integer, primary_key=True)
    tvdb_id = Column(String(50), ForeignKey("watch_list.tvdb_id"), nullable=False, index=True)
    
    # Episode Info (NULL wenn nicht gematcht)
    season = Column(Integer, nullable=True)
    episode = Column(Integer, nullable=True)
    episode_title = Column(String(500), nullable=True)  # TVDB Titel, NULL wenn unmatched

    # Mediathek
    mediathek_title = Column(String(500), nullable=False)
    mediathek_platform = Column(String(50))
    media_url = Column(Text, nullable=False)
    quality = Column(String(50))

    # Matching Info
    match_confidence = Column(Integer, nullable=True)  # 0-100, NULL wenn unmatched
    match_type = Column(String(50), nullable=True)     # "title", "date", "guest", etc.

    # Lifecycle
    created_at = Column(DateTime, server_default=func.now())
    expires_at = Column(DateTime, nullable=False)
    
    __table_args__ = (
        Index('idx_tvdb_se', 'tvdb_id', 'season', 'episode'),
    )
