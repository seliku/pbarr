from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class Show(Base):
    __tablename__ = "shows"
    
    id = Column(Integer, primary_key=True)
    tvdb_id = Column(String, unique=True, nullable=False)  # TVDB ID für Matching
    source_id = Column(String)  # ARD/ZDF interne ID
    source = Column(String)  # "ard", "zdf", "3sat"
    
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    language = Column(String, default="de")
    
    genres = Column(String, nullable=True)  # JSON oder comma-separated
    rating = Column(String, nullable=True)
    
    last_indexed = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    enabled = Column(Boolean, default=True)
    
    def __repr__(self):
        return f"<Show {self.title} (TVDB: {self.tvdb_id})>"
