"""
TVDB API v4 Client
"""
import logging
from typing import Optional, List
import aiohttp
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import json
import traceback


from app.models.tvdb_cache import TVDBCache
from app.utils.network import create_aiohttp_session, get_proxy_for_url


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
    
    async def get_episodes(self, tvdb_id: int, cache_to_db: bool = True) -> List[dict]:
        """
        Fetch TVDB episodes
        
        Args:
            tvdb_id: TVDB Series ID
            cache_to_db: Speichere in DB
        
        Returns:
            List of episodes
        """
        tvdb_id_str = str(tvdb_id)
        logger.info(f"Fetching TVDB episodes #{tvdb_id_str}")
        
        try:
            proxy_url = get_proxy_for_url(self.BASE_URL)
            async with create_aiohttp_session(proxy_url=proxy_url) as session:
                if not await self._get_token(session):
                    return []

                headers = {'Authorization': f'Bearer {self.access_token}'}

                # Hole Show-Info zuerst
                show_name = await self._get_show_name(tvdb_id_str, headers, session)

                url = f"{self.BASE_URL}/series/{tvdb_id_str}/episodes/official"

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
                            response_data = data.get('data', {})
                            eps_list = response_data.get('episodes', []) if isinstance(response_data, dict) else []

                            logger.info(f"Page {page}: {len(eps_list)} items")

                            # Parse Episodes
                            for ep in eps_list:
                                try:
                                    if not isinstance(ep, dict):
                                        continue

                                    s = ep.get('seasonNumber')
                                    e = ep.get('number')
                                    name = ep.get('name')
                                    aired = ep.get('aired')
                                    overview = ep.get('overview', '')

                                    if s is None or e is None:
                                        continue

                                    episode_data = {
                                        'season': s,
                                        'episode': e,
                                        'name': name or '',
                                        'overview': overview,
                                        'aired': aired,
                                    }

                                    all_episodes.append(episode_data)

                                except Exception as ie:
                                    logger.error(f"Item error: {ie}")
                                    continue

                            # Pagination
                            links = data.get('links', {})
                            if links.get('next'):
                                url = links['next']
                                page += 1
                            else:
                                break

                    except Exception as pe:
                        logger.error(f"Page error: {pe}")
                        break

                logger.info(f"✓ Total: {len(all_episodes)} episodes")

                # Step 2: Cache in DB
                if cache_to_db and self.db and len(all_episodes) > 0:
                    self._cache_episodes_to_db(tvdb_id_str, show_name, all_episodes)

                return all_episodes
        
        except Exception as e:
            logger.error(f"Fetch error: {e}")
            logger.error(traceback.format_exc())
            return []
    
    async def _get_show_name(self, tvdb_id: str, headers: dict, session: aiohttp.ClientSession) -> str:
        """Hole Show-Namen"""
        try:
            url = f"{self.BASE_URL}/series/{tvdb_id}"
            async with session.get(url, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    name = data.get('data', {}).get('name', f'Show_{tvdb_id}')
                    logger.info(f"✓ Show name: {name}")
                    return name
        except Exception as e:
            logger.debug(f"Show name fetch failed: {e}")

        return f'Show_{tvdb_id}'

    async def get_show_titles(self, tvdb_id: int) -> List[str]:
        """
        Get all titles for a show (primary + alternate titles)

        Returns:
            List of all title variants for this show
        """
        titles = []

        try:
            proxy_url = get_proxy_for_url(self.BASE_URL)
            async with create_aiohttp_session(proxy_url=proxy_url) as session:
                if not await self._get_token(session):
                    logger.warning(f"Could not get TVDB token for titles fetch")
                    return titles

                headers = {'Authorization': f'Bearer {self.access_token}'}

                # Get primary title
                primary_title = await self._get_show_name(str(tvdb_id), headers, session)
                if primary_title and primary_title != f'Show_{tvdb_id}':
                    titles.append(primary_title)
                    logger.debug(f"✓ Primary title: {primary_title}")

                # Get alternate titles (translations)
                # Try different endpoints - TVDB API might have changed
                translation_urls = [
                    f"{self.BASE_URL}/series/{tvdb_id}/translations",
                    f"{self.BASE_URL}/series/{tvdb_id}/translations/de",  # German specific
                    f"{self.BASE_URL}/series/{tvdb_id}/translations/en",  # English
                ]

                for url in translation_urls:
                    try:
                        logger.debug(f"Trying translations URL: {url}")
                        async with session.get(url, headers=headers, timeout=10) as resp:
                            logger.debug(f"Translations API response: {resp.status}")

                            if resp.status == 200:
                                data = await resp.json()
                                logger.debug(f"Translations data: {data}")

                                # Handle different response formats
                                translations = []
                                if isinstance(data.get('data'), list):
                                    translations = data.get('data', [])
                                elif isinstance(data.get('data'), dict):
                                    # Single translation object
                                    translations = [data.get('data', {})]

                                for trans in translations:
                                    if isinstance(trans, dict):
                                        title = trans.get('name')
                                        if title and title not in titles:
                                            titles.append(title)
                                            logger.info(f"✓ Alternate title: {title}")

                                # If we found translations, break
                                if translations:
                                    break

                    except Exception as e:
                        logger.debug(f"Translations URL {url} failed: {e}")
                        continue

                logger.info(f"✓ Found {len(titles)} title variants for TVDB {tvdb_id}: {titles}")
                return titles

        except Exception as e:
            logger.error(f"Show titles fetch error: {e}")
            return titles
    
    def _cache_episodes_to_db(self, tvdb_id: str, show_name: str, episodes: List[dict]):
        """Speichere Episodes in DB - ignore duplicates"""
        try:
            logger.info(f"Caching {len(episodes)} episodes to DB...")
            
            cached = 0
            skipped = 0
            
            for ep in episodes:
                try:
                    # Prüfe ob bereits existiert
                    existing = self.db.query(TVDBCache).filter(
                        TVDBCache.tvdb_id == tvdb_id,
                        TVDBCache.season == ep['season'],
                        TVDBCache.episode == ep['episode']
                    ).first()
                    
                    if existing:
                        skipped += 1
                        continue
                    
                    # Parse aired date
                    aired_date = None
                    if ep.get('aired'):
                        try:
                            aired_date = datetime.fromisoformat(ep['aired']).date()
                        except:
                            pass
                    
                    # Create cache entry
                    cache_entry = TVDBCache(
                        tvdb_id=tvdb_id,
                        show_name=show_name,
                        season=ep['season'],
                        episode=ep['episode'],
                        episode_name=ep['name'],
                        description=ep.get('overview', ''),
                        aired_date=aired_date,
                    )
                    self.db.add(cache_entry)
                    cached += 1
                    
                    # Commit pro Episode um duplicates zu vermeiden
                    if cached % 100 == 0:
                        self.db.commit()
                
                except IntegrityError as ie:
                    logger.debug(f"Duplicate skipped: S{ep['season']}E{ep['episode']}")
                    self.db.rollback()
                    skipped += 1
                except Exception as e:
                    logger.error(f"Episode cache error: {e}")
                    self.db.rollback()
            
            # Final commit
            self.db.commit()
            logger.info(f"✅ Cached {cached} new episodes ({skipped} skipped)")
        
        except Exception as e:
            logger.error(f"Cache error: {e}", exc_info=True)
            self.db.rollback()
