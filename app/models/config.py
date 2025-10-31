from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import json

Base = declarative_base()

class Config(Base):
    __tablename__ = "config"
    
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, nullable=False)
    value = Column(Text)
    module = Column(String, default="core")  # "tvdb", "ard", "core"
    secret = Column(Boolean, default=False)  # Verschlüsselt in DB?
    data_type = Column(String, default="string")  # string, int, bool, json
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    description = Column(String, nullable=True)
    
    def __repr__(self):
        return f"<Config {self.key}={self.value[:20]}...>"
    
    @property
    def typed_value(self):
        """Gibt value als korrekten Typ zurück"""
        if self.data_type == "bool":
            return self.value.lower() in ("true", "1", "yes")
        elif self.data_type == "int":
            return int(self.value)
        elif self.data_type == "json":
            return json.loads(self.value)
        return self.value
