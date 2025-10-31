from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from dataclasses import dataclass

@dataclass
class Episode:
    season: int
    episode_number: int
    title: str
    description: Optional[str] = None
    url: Optional[str] = None
    air_date: Optional[str] = None

@dataclass
class Show:
    source_id: str
    title: str
    description: Optional[str] = None
    tvdb_id: Optional[str] = None

class MediathekModule(ABC):
    """Base Klasse für alle Mediathek-Module"""
    
    name: str = "Unknown"
    description: str = ""
    enabled: bool = True
    version: str = "1.0.0"
    
    @abstractmethod
    async def search(self, query: str) -> List[Show]:
        """Suche nach Shows"""
        pass
    
    @abstractmethod
    async def get_episodes(self, show_id: str) -> List[Episode]:
        """Alle Episodes einer Show abrufen"""
        pass
    
    @abstractmethod
    async def get_episode(self, show_id: str, season: int, episode: int) -> Optional[Episode]:
        """Einzelne Episode abrufen"""
        pass
    
    async def validate_episode_url(self, url: str) -> bool:
        """Validiert ob Episode URL noch verfügbar ist"""
        return True
