"""
MediathekViewWeb Source Module
Sucht in gemeinsamen Index: ARD, ZDF, 3Sat, etc.
"""
import logging
from typing import List, Optional
import aiohttp
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

class MediathekViewWebModule:
    name = "MediathekViewWeb"
    description = "Unified search for ARD, ZDF, 3Sat, Arte, etc."
    version = "0.1.0"
    
    BASE_URL = "https://mediathekviewweb.de/feed"
    
    @staticmethod
    async def search(query: str, channel: str = "ard") -> List[dict]:
        """
        Sucht in MediathekViewWeb
        
        Query Format: !ard #Show,Name >30
        - !ard = Channel filter (ARD)
        - #Show,Name = Show title
        - >30 = Duration > 30 min
        """
        try:
            # Build feed query
            feed_query = f"!{channel}%20%23{query.replace(' ', '%2C')}%20%3E30"
            url = f"{MediathekViewWebModule.BASE_URL}?query={feed_query}"
            
            logger.info(f"Searching MediathekViewWeb: {url}")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as resp:
                    if resp.status == 200:
                        content = await resp.text()
                        
                        # Parse RSS/XML
                        root = ET.fromstring(content)
                        
                        episodes = []
                        for item in root.findall('.//item'):
                            ep = {
                                'title': item.findtext('title', ''),
                                'description': item.findtext('description', ''),
                                'link': item.findtext('link', ''),
                                'channel': item.findtext('channel', ''),
                                'pubDate': item.findtext('pubDate', ''),
                            }
                            episodes.append(ep)
                            logger.debug(f"Found: {ep['title']}")
                        
                        logger.info(f"✓ Found {len(episodes)} episodes")
                        return episodes
                    else:
                        logger.error(f"MediathekViewWeb returned HTTP {resp.status}")
                        return []
        
        except Exception as e:
            logger.error(f"MediathekViewWeb search error: {e}")
            return []
    
    @staticmethod
    async def get_download_url(episode_link: str) -> Optional[str]:
        """
        Extrahiert echte Download-URL via yt-dlp
        """
        try:
            import subprocess
            import json
            
            logger.info(f"Extracting download URL: {episode_link}")
            
            # yt-dlp holt die direkten URLs
            cmd = [
                'yt-dlp',
                '-f', 'best',
                '-g',  # Print URL only
                episode_link
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                url = result.stdout.strip().split('\n')[0]  # First line is video URL
                logger.info(f"✓ Got download URL")
                return url
            else:
                logger.error(f"yt-dlp failed: {result.stderr}")
                return None
        
        except Exception as e:
            logger.error(f"Download URL extraction error: {e}")
            return None
