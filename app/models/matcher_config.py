from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from datetime import datetime
from app.database import Base

class MatcherConfig(Base):
    __tablename__ = "matcher_configs"
    
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)  # z.B. "ard_default", "zdf_custom"
    source = Column(String, nullable=False)  # "ard", "zdf", etc.
    
    # Matching Strategy
    strategy = Column(String, default="regex")  # "regex", "pattern", "custom"
    
    # Regex Patterns
    title_pattern = Column(String, nullable=True)  # z.B. r'^(.+?)\s+(?:S\d+\s+)?(?:Folge\s+)?(\d+)'
    season_pattern = Column(String, nullable=True)  # z.B. r'S(\d+)' or 'season_index'
    episode_pattern = Column(String, nullable=True)  # z.B. r'E(\d+)' or 'episode_index'
    
    # Extraktions-Felder
    title_group = Column(Integer, default=1)  # Welche Regex-Group für Title?
    season_group = Column(Integer, default=2)  # Welche Regex-Group für Season?
    episode_group = Column(Integer, default=3)  # Welche Regex-Group für Episode?
    
    # Fallback bei fehlender Season
    default_season = Column(Integer, default=1)
    
    # Test Strings für Validierung
    test_string = Column(String, nullable=True)  # z.B. "Die Sendung mit der Maus - Folge 42"
    
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<MatcherConfig {self.name} ({self.source})>"
