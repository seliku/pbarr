"""
ARD Mediathek Service - Sucht und extrahiert Episodes
"""
import logging
import aiohttp
from typing import List, Optional
from datetime import datetime

from app.utils.network import create_aiohttp_session, get_proxy_for_url

logger = logging.getLogger(__name__)

class ARDService:
    """ARD Mediathek API Integration"""
    
    BASE_URL = "https://www.ardmediathek.de/api"
    
    @staticmethod
    async def search_show(show_title: str) -> Optional[dict]:
        """Sucht Show in ARD Mediathek"""
        try:
            proxy_url = get_proxy_for_url(ARDService.BASE_URL)
            async with create_aiohttp_session(proxy_url=proxy_url) as session:
                search_url = f"{ARDService.BASE_URL}/pages/searches/results?searchString={show_title}&pageSize=20"

                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }

                async with session.get(search_url, headers=headers, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        # Finde beste Match (Series)
                        if "teasers" in data:
                            for teaser in data["teasers"]:
                                if teaser.get("type") == "series":
                                    show_info = {
                                        "ard_id": teaser.get("id", ""),
                                        "title": teaser.get("title", ""),
                                        "description": teaser.get("synopsis", ""),
                                        "link": teaser.get("links", {}).get("self", {}).get("href", ""),
                                    }
                                    logger.info(f"✓ Found ARD show: {show_info['title']}")
                                    return show_info
                        
                        logger.warning(f"No series found for '{show_title}'")
                        return None
                    else:
                        logger.error(f"ARD search failed: HTTP {resp.status}")
        
        except Exception as e:
            logger.error(f"ARD search error: {e}")
        
        return None
    
    @staticmethod
    async def get_episodes(ard_show_id: str) -> List[dict]:
        """Holt alle Episodes einer ARD Show"""
        episodes = []
        
        try:
            proxy_url = get_proxy_for_url(ARDService.BASE_URL)
            async with create_aiohttp_session(proxy_url=proxy_url) as session:
                show_url = f"{ARDService.BASE_URL}/pages/ard/shows/{ard_show_id}"

                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }

                async with session.get(show_url, headers=headers, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        if "teasers" in data:
                            for idx, teaser in enumerate(data["teasers"]):
                                ep = {
                                    "ard_id": teaser.get("id", ""),
                                    "title": teaser.get("title", ""),
                                    "description": teaser.get("synopsis", ""),
                                    "url": teaser.get("links", {}).get("self", {}).get("href", ""),
                                    "publication_date": teaser.get("publicationStartDate", ""),
                                    "duration": teaser.get("duration"),
                                    "index": idx + 1  # Fallback Episode Nummer
                                }
                                episodes.append(ep)
                                logger.debug(f"Found ARD episode: {ep['title']}")
                        
                        logger.info(f"✓ Got {len(episodes)} episodes from ARD")
                        return episodes
                    else:
                        logger.error(f"ARD get_episodes failed: HTTP {resp.status}")
        
        except Exception as e:
            logger.error(f"ARD get_episodes error: {e}")
        
        return []
