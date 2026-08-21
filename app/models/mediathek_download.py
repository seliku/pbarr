from sqlalchemy import Column, String, DateTime, Integer, BigInteger, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class MediathekDownload(Base):
    """
    One row per item fetched from the Mediathek.

    Identity is the source URL, not a season/episode pair. Two independent TVDB
    consumers produced conflicting numbering, so numbers are not used as keys
    any more - see migrate_mediathek_direct.py for the full story.
    """

    __tablename__ = "mediathek_downloads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    watch_key = Column(String(50), nullable=False, index=True)
    show_name = Column(String(255), nullable=False)
    source_url = Column(Text, nullable=False)

    channel = Column(String(100))
    topic = Column(String(255))
    title = Column(String(500))
    aired = Column(DateTime)
    duration_seconds = Column(Integer)
    quality = Column(String(20))

    file_path = Column(Text)
    file_size = Column(BigInteger)
    downloaded_at = Column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("watch_key", "source_url", name="uq_watch_source"),)
