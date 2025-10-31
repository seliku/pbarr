import logging
import aiohttp
from xml.etree import ElementTree as ET
from datetime import datetime, timedelta
from sqlalchemy.orm import Session


from app.models.watch_list import WatchList
from app.models.mediathek_cache import MediathekCache
from app.models.tvdb_cache import TVDBCache
from app.database import SessionLocal
from app.services.episode_matcher import EpisodeMatcher


logger = logging.getLogger(__name__)


class MediathekCacher:
    """Cacht Mediathek-Daten stündlich für beobachtete Shows"""
    
    CACHE_DURATION_DAYS = 30
    
    async def sync_watched_shows(self):
        """Hourly: Cache alle beobachteten Shows"""
        db = SessionLocal()
        try:
            logger.info("🔄 Starting Mediathek cache sync...")
            
            watch_list = db.query(WatchList).all()
            
            if not watch_list:
                logger.info("No shows in watch list")
                return
            
            logger.info(f"Found {len(watch_list)} shows to cache")
            
            cached_count = 0
            for watched in watch_list:
                count = await self._cache_show(watched.tvdb_id, watched.show_name, db)
                cached_count += count
            
            logger.info(f"✅ Cached {cached_count} episodes total")
        
        except Exception as e:
            logger.error(f"❌ Cache sync error: {e}", exc_info=True)
        finally:
            db.close()
    
    async def _cache_show(self, tvdb_id: str, show_name: str, db: Session) -> int:
        """Cache eine Show auf MediathekViewWeb mit Episode-Matching"""
        try:
            logger.info(f"  Caching: {show_name} (TVDB {tvdb_id})")
            
            # Step 1: Hole TVDB Episodes
            tvdb_cache_entries = db.query(TVDBCache).filter(
                TVDBCache.tvdb_id == tvdb_id
            ).all()
            
            if not tvdb_cache_entries:
                logger.warning(f"  No TVDB cache for {tvdb_id}")
                return 0
            
            # Convert zu dict format für Matcher
            tvdb_episodes = []
            for cache in tvdb_cache_entries:
                tvdb_episodes.append({
                    'season': cache.season,
                    'episode': cache.episode,
                    'name': cache.episode_name,
                    'aired': cache.aired_date.isoformat() if cache.aired_date else None,
                    'overview': cache.description or ''
                })
            
            logger.debug(f"  Loaded {len(tvdb_episodes)} TVDB episodes")
            
            # Step 2: Suche auf MediathekViewWeb
            query_name = show_name.replace(' ', '%2C')
            feed_url = f"https://mediathekviewweb.de/feed?query=!ard%20%23{query_name}%20%3E20"
            
            mediathek_results = []
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(feed_url, timeout=15) as resp:
                        if resp.status != 200:
                            logger.warning(f"  Feed failed: {resp.status}")
                            return 0
                        
                        content = await resp.text()
                        root = ET.fromstring(content)
                        
                        for item in root.findall('.//item'):
                            title = item.findtext('title', '')
                            link = item.findtext('link', '')
                            pub_date = item.findtext('pubDate', '')
                            description = item.findtext('description', '')
                            
                            if not link:
                                continue
                            
                            mediathek_results.append({
                                'title': title,
                                'link': link,
                                'pub_date': pub_date,
                                'description': description,
                            })
                except Exception as e:
                    logger.warning(f"  Feed fetch error: {e}")
                    return 0
            
            if not mediathek_results:
                logger.info(f"  No results for {show_name}")
                return 0
            
            logger.debug(f"  Found {len(mediathek_results)} Mediathek results")
            
            # Step 3: Match mit Matcher
            matcher = EpisodeMatcher(db)
            cached = 0
            
            for mvw_ep in mediathek_results:
                # Matche Episode
                match_result = matcher.match_episode(mvw_ep, tvdb_episodes)
                
                if not match_result:
                    continue
                
                # Prüfe ob bereits im Cache
                existing = db.query(MediathekCache).filter(
                    MediathekCache.tvdb_id == tvdb_id,
                    MediathekCache.season == match_result.season,
                    MediathekCache.episode == match_result.episode,
                    MediathekCache.expires_at > datetime.utcnow()
                ).first()
                
                if existing:
                    continue
                
                # Erstelle Cache-Eintrag
                cache_entry = MediathekCache(
                    tvdb_id=tvdb_id,
                    season=match_result.season,
                    episode=match_result.episode,
                    episode_title=mvw_ep['title'],
                    mediathek_platform="ard",
                    media_url=mvw_ep['link'],
                    quality=self._guess_quality(mvw_ep['title']),
                    expires_at=datetime.utcnow() + timedelta(days=self.CACHE_DURATION_DAYS)
                )
                db.add(cache_entry)
                cached += 1
            
            if cached > 0:
                db.commit()
                logger.info(f"  ✅ Cached {cached} new episodes")
            
            return cached
        
        except Exception as e:
            logger.error(f"  Cache error for {show_name}: {e}", exc_info=True)
            return 0
    
    def _guess_quality(self, title: str) -> str:
        """Guess quality from title"""
        if "1080" in title:
            return "1080p"
        elif "720" in title or "HD" in title:
            return "720p"
        else:
            return "480p"
    
    async def cleanup_expired(self):
        """Daily: Lösche abgelaufene Cache-Einträge"""
        db = SessionLocal()
        try:
            logger.info("🧹 Starting cache cleanup...")
            
            expired = db.query(MediathekCache).filter(
                MediathekCache.expires_at < datetime.utcnow()
            ).delete()
            
            if expired > 0:
                db.commit()
                logger.info(f"✅ Deleted {expired} expired cache entries")
            else:
                logger.info("No expired entries")
        
        except Exception as e:
            logger.error(f"❌ Cleanup error: {e}")
        finally:
            db.close()
    
    async def cleanup_unwatched(self):
        """Daily: Lösche Cache für nicht mehr beobachtete Shows"""
        db = SessionLocal()
        try:
            logger.info("🧹 Cleaning up unwatched shows...")
            
            cutoff = datetime.utcnow() - timedelta(days=30)
            inactive = db.query(WatchList).filter(
                WatchList.last_accessed < cutoff
            ).all()
            
            if not inactive:
                logger.info("No inactive shows")
                return
            
            logger.info(f"Found {len(inactive)} inactive shows (>30 days)")
            
            for watch in inactive:
                deleted = db.query(MediathekCache).filter(
                    MediathekCache.tvdb_id == watch.tvdb_id
                ).delete()
                
                db.delete(watch)
                db.commit()
                
                logger.info(f"  Deleted {deleted} cache entries for TVDB {watch.tvdb_id}")
            
            logger.info(f"✅ Cleanup complete")
        
        except Exception as e:
            logger.error(f"❌ Cleanup error: {e}")
        finally:
            db.close()


cacher = MediathekCacher()
