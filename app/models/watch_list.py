from sqlalchemy import Column, String, DateTime, Integer, Boolean
from sqlalchemy.sql import func
from app.database import Base


class WatchList(Base):
    __tablename__ = "watch_list"

    tvdb_id = Column(String(50), primary_key=True)
    show_name = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())
    last_accessed = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # New fields for Sonarr integration
    tagged_in_sonarr = Column(Boolean, default=False)
    tagged_at = Column(DateTime, nullable=True)
    pbarr_tag_id = Column(Integer, nullable=True)
    sonarr_series_id = Column(Integer, nullable=True)
    import_source = Column(String(50), default="manual")  # manual|webhook|sonarr_import
    episodes_found = Column(Integer, default=0)
    mediathek_episodes_count = Column(Integer, default=0)  # Cached count of available mediathek episodes

    # Filter fields for episode matching
    min_duration = Column(Integer, default=0)  # Minimum episode duration in minutes
    max_duration = Column(Integer, default=360)  # Maximum episode duration in minutes
    exclude_keywords = Column(String(1000), default="klare Sprache,Audiodeskription,Gebärdensprache")  # Comma-separated keywords to exclude
    include_senders = Column(String(1000), default="")  # Comma-separated senders to include

    # Search title filtering for Mediathek searches
    search_title_filter = Column(Boolean, default=False)  # Enable/disable search title filtering
    custom_search_title = Column(String(255), default="")  # Custom search title (overrides auto-generated)
