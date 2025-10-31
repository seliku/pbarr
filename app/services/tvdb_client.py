"""
TVDB API v4 Client
"""
import logging
from typing import Optional, List
import aiohttp
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import json
import traceback


logger = logging.getLogger(__name__)


class TVDBClient:
    BASE_URL = "https://api4.thetvdb.com/v4"
    CACHE_TTL = 7 * 24 * 60 * 60
    
    def __init__(self, api_key: str, db: Session = None):
        self.api_key = api_key
        self.db = db
        self.access_token = None
        self.token_expires = None
    
    async def _get_token(self, session: aiohttp.ClientSession) -> bool:
        try:
            if self.access_token and self.token_expires and datetime.now() < self.token_expires:
                return True
            
            url = f"{self.BASE_URL}/login"
            async with session.post(url, json={'apikey': self.api_key}, timeout=10) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    self.access_token = result.get('data', {}).get('token')
                    self.token_expires = datetime.now() + timedelta(days=25)
                    logger.info("✓ TVDB token acquired")
                    return True
                else:
                    logger.error(f"TVDB login failed: HTTP {resp.status}")
                    return False
        except Exception as e:
            logger.error(f"Token error: {e}")
            return False
    
    async def get_episodes(self, tvdb_id: int) -> List[dict]:
        logger.info(f"Fetching TVDB episodes #{tvdb_id}")
        
        try:
            async with aiohttp.ClientSession() as session:
                if not await self._get_token(session):
                    return []
                
                headers = {'Authorization': f'Bearer {self.access_token}'}
                url = f"{self.BASE_URL}/series/{tvdb_id}/episodes/official"
                
                all_episodes = []
                page = 0
                
                while url and page < 1000:
                    logger.info(f"Fetching page {page}: {url}")
                    
                    try:
                        async with session.get(url, headers=headers, timeout=10) as resp:
                            logger.info(f"HTTP {resp.status}")
                            
                            if resp.status != 200:
                                logger.error(f"HTTP {resp.status}")
                                break
                            
                            data = await resp.json()
                            logger.info(f"Response keys: {list(data.keys())}")
                            
                            # ✅ KORREKT: episodes ist im data['data']['episodes'] Feld
                            response_data = data.get('data', {})
                            eps_list = response_data.get('episodes', []) if isinstance(response_data, dict) else []
                            
                            logger.info(f"Page {page}: {len(eps_list)} items")
                            
                            # DEBUG first item
                            if eps_list and len(eps_list) > 0:
                                first = eps_list[0]
                                logger.info(f"First item type: {type(first)}")
                                logger.info(f"First item keys: {list(first.keys()) if isinstance(first, dict) else 'N/A'}")
                                logger.info(f"First item: {json.dumps(first, default=str)[:500]}")
                            
                            # Iteriere über echte Episode-Objects
                            for ep in eps_list:
                                try:
                                    if not isinstance(ep, dict):
                                        logger.warning(f"Item not dict: {type(ep)}")
                                        continue
                                    
                                    s = ep.get('seasonNumber')
                                    e = ep.get('number')
                                    name = ep.get('name')
                                    aired = ep.get('aired')
                                    
                                    logger.debug(f"Item: S{s}E{e} - {name} ({aired})")
                                    
                                    if s is None or e is None:
                                        logger.debug(f"Skip: S={s}, E={e}")
                                        continue
                                    
                                    all_episodes.append({
                                        'season': s,
                                        'episode': e,
                                        'name': name or '',
                                        'overview': ep.get('overview', ''),
                                        'aired': aired,
                                    })
                                
                                except Exception as ie:
                                    logger.error(f"Item error: {ie}")
                                    continue
                            
                            # Pagination
                            links = data.get('links', {})
                            if links.get('next'):
                                url = links['next']
                                page += 1
                            else:
                                logger.info(f"No more pages")
                                break
                    
                    except Exception as pe:
                        logger.error(f"Page error: {pe}")
                        logger.error(traceback.format_exc())
                        break
                
                logger.info(f"✓ Total: {len(all_episodes)} episodes")
                return all_episodes
        
        except Exception as e:
            logger.error(f"Fetch error: {e}")
            logger.error(traceback.format_exc())
            return []
