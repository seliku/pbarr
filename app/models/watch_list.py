from sqlalchemy import Column, String, DateTime, Integer
from sqlalchemy.sql import func
from app.database import Base


class WatchList(Base):
    __tablename__ = "watch_list"
    
    tvdb_id = Column(String(50), primary_key=True)
    show_name = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())
    last_accessed = Column(DateTime, server_default=func.now(), onupdate=func.now())
