"""
ARD Mediathek Source Module
Scraped die ARD Mediathek via yt-dlp URLs
"""

from app.modules.sources.base import MediathekModule, Show, Episode
from typing import List, Optional
import aiohttp
import logging
import asyncio
from datetime import datetime
import json

logger = logging.getLogger(__name__)

class ARDModule(MediathekModule):
    name = "ARD"
    description = "Das Erste - ARD Mediathek (yt-dlp integration)"
    version = "0.2.0"
    
    # ARD Mediathek URLs
    BASE_URL = "https://www.ardmediathek.de"
    API_BASE = "https://www.ardmediathek.de/api"
    
    async def search(self, query: str) -> List[Show]:
        """Suche nach Shows in ARD Mediathek"""
        try:
            async with aiohttp.ClientSession() as session:
                # ARD Search API
                search_url = f"{self.API_BASE}/pages/searches/results?searchString={query}&pageSize=50"
                
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                
                async with session.get(search_url, headers=headers, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        shows = []
                        
                        # Parse search results
                        if "teasers" in data:
                            for teaser in data["teasers"][:20]:
                                if teaser.get("type") == "series":
                                    show = Show(
                                        source_id=teaser.get("id", ""),
                                        title=teaser.get("title", ""),
                                        description=teaser.get("synopsis", ""),
                                        tvdb_id=None
                                    )
                                    shows.append(show)
                                    logger.debug(f"Found ARD show: {show.title}")
                        
                        return shows
                    else:
                        logger.error(f"ARD search failed: HTTP {resp.status}")
        
        except Exception as e:
            logger.error(f"ARD search error: {e}")
        
        return []
    
    async def get_episodes(self, show_id: str) -> List[Episode]:
        """Alle Episodes einer Show abrufen"""
        episodes = []
        
        try:
            async with aiohttp.ClientSession() as session:
                # ARD Show Details
                show_url = f"{self.API_BASE}/pages/ard/shows/{show_id}"
                
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                
                async with session.get(show_url, headers=headers, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        # Parse episodes from teasers
                        if "teasers" in data:
                            for idx, teaser in enumerate(data["teasers"]):
                                # ARD strukturiert anders - kein S##E## Format
                                # Wir nutzen Index für Episoden-Nummern
                                ep = Episode(
                                    season=1,
                                    episode_number=idx + 1,
                                    title=teaser.get("title", ""),
                                    description=teaser.get("synopsis", ""),
                                    url=teaser.get("links", {}).get("self", {}).get("href", ""),
                                    air_date=teaser.get("publicationStartDate", "")
                                )
                                episodes.append(ep)
                                logger.debug(f"Found episode: S1E{idx+1}: {ep.title}")
        
        except Exception as e:
            logger.error(f"ARD get_episodes error: {e}")
        
        return episodes
    
    async def get_episode(self, show_id: str, season: int, episode: int) -> Optional[Episode]:
        """Einzelne Episode abrufen"""
        episodes = await self.get_episodes(show_id)
        
        for ep in episodes:
            if ep.season == season and ep.episode_number == episode:
                return ep
        
        return None
    
    async def get_download_url(self, episode_url: str) -> Optional[str]:
        """
        Extrahiert echte Download URL aus ARD Mediathek
        Nutzt yt-dlp im Hintergrund
        """
        try:
            import subprocess
            import json
            
            # yt-dlp nutzen um m3u8 oder mp4 URL zu extrahieren
            cmd = [
                'yt-dlp',
                '-f', 'best',
                '-j',  # JSON output
                '--no-warnings',
                episode_url
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                try:
                    data = json.loads(result.stdout)
                    # Beste verfügbare URL
                    if "url" in data:
                        return data["url"]
                except json.JSONDecodeError:
                    pass
            
            logger.warning(f"Could not extract URL from {episode_url}")
        
        except Exception as e:
            logger.error(f"Download URL extraction error: {e}")
        
        return None
    
    async def validate_episode_url(self, url: str) -> bool:
        """Prüft ob Episode URL noch verfügbar ist"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.head(url, timeout=5) as resp:
                    return resp.status == 200
        except:
            return False
