from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from datetime import datetime
from app.database import Base

class Show(Base):
    __tablename__ = "shows"
    
    id = Column(Integer, primary_key=True)
    tvdb_id = Column(String, unique=True, nullable=False)
    source_id = Column(String)
    source = Column(String)
    
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    language = Column(String, default="de")
    
    genres = Column(String, nullable=True)
    rating = Column(String, nullable=True)
    
    last_indexed = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    enabled = Column(Boolean, default=True)
    
    def __repr__(self):
        return f"<Show {self.title} (TVDB: {self.tvdb_id})>"
