from app.modules.sources.base import MediathekModule, Show, Episode
from typing import List, Optional
import aiohttp
import logging

logger = logging.getLogger(__name__)

class ARDModule(MediathekModule):
    name = "ARD"
    description = "Das Erste - ARD Mediathek"
    version = "0.1.0"
    
    # ARD API Endpoints (vereinfacht für MVP)
    BASE_URL = "https://www.ardmediathek.de"
    API_URL = "https://api.ardmediathek.de/page-service"
    
    async def search(self, query: str) -> List[Show]:
        """Suche ARD nach Shows"""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.API_URL}/pages/searches/results?searchString={query}"
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        shows = []
                        
                        # Parsing ARD API Response (simplified)
                        if "teasers" in data:
                            for teaser in data["teasers"][:10]:
                                show = Show(
                                    source_id=teaser.get("id", ""),
                                    title=teaser.get("title", ""),
                                    description=teaser.get("description", ""),
                                    tvdb_id=None  # Wird später gematcht
                                )
                                shows.append(show)
                        
                        return shows
        except Exception as e:
            logger.error(f"ARD search error: {e}")
        
        return []
    
    async def get_episodes(self, show_id: str) -> List[Episode]:
        """Alle Episodes einer ARD Show"""
        episodes = []
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.API_URL}/pages/ard/shows/{show_id}"
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        # Parsing episodes (simplified)
                        if "teasers" in data:
                            for teaser in data["teasers"]:
                                ep = Episode(
                                    season=0,  # ARD strukturiert anders
                                    episode_number=0,
                                    title=teaser.get("title", ""),
                                    description=teaser.get("description", ""),
                                    url=teaser.get("links", {}).get("play", {}).get("href", ""),
                                    air_date=teaser.get("publicationStartDate", "")
                                )
                                episodes.append(ep)
        except Exception as e:
            logger.error(f"ARD get_episodes error: {e}")
        
        return episodes
    
    async def get_episode(self, show_id: str, season: int, episode: int) -> Optional[Episode]:
        """Einzelne Episode abrufen"""
        episodes = await self.get_episodes(show_id)
        
        # Simplified matching
        if episodes:
            return episodes[0]  # Placeholder
        
        return None
