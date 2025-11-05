import logging
import aiohttp
import shutil
from xml.etree import ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy.orm import Session
import subprocess
import asyncio
from typing import Optional


from app.models.watch_list import WatchList
from app.models.mediathek_cache import MediathekCache
from app.models.tvdb_cache import TVDBCache
from app.models.episode_monitoring_state import EpisodeMonitoringState
from app.database import SessionLocal
from app.services.episode_matcher import EpisodeMatcher
from app.services.sonarr_webhook import SonarrWebhookManager
from app.models.config import Config
from app.utils.network import create_aiohttp_session, create_httpx_client

# Hardcoded download path in container (maps to completed directory on host)
PBARR_DOWNLOAD_PATH = Path("/app/downloads/completed")


logger = logging.getLogger(__name__)


class MediathekCacher:
    """Cacht Mediathek-Daten stündlich für beobachtete Shows"""
    
    CACHE_DURATION_DAYS = 30
    
    async def sync_watched_shows(self):
        """Hourly: Cache nur manuell getaggte Shows + Smart Monitoring Detection"""
        db = SessionLocal()
        try:
            logger.info("🔄 Starting Mediathek cache sync for tagged shows...")

            # Check for orphaned series before processing
            try:
                logger.info("🧹 Starting orphaned series cleanup...")
                await self._cleanup_orphaned_series(db)
                logger.info("✅ Orphaned series cleanup completed")
            except Exception as e:
                logger.error(f"❌ Orphaned series cleanup failed: {e}")

            # NUR Serien die bereits manuell in Sonarr getaggt wurden
            watch_list = db.query(WatchList).filter(WatchList.tagged_in_sonarr == True).all()

            if not watch_list:
                logger.info("No manually tagged shows in watch list")
                return

            logger.info(f"Found {len(watch_list)} manually tagged shows to cache")

            # SMART MONITORING DETECTION: Check for monitoring changes first
            await self._detect_monitoring_changes(db)

            cached_count = 0
            for watched in watch_list:
                count = await self._cache_show(watched.tvdb_id, watched.show_name, db)
                cached_count += count

            logger.info(f"✅ Cached {cached_count} episodes total for tagged shows")

        except Exception as e:
            logger.error(f"❌ Cache sync error: {e}", exc_info=True)
        finally:
            db.close()
    
    async def _cache_show(self, tvdb_id: str, show_name: str, db: Session) -> int:
        """Cache eine Show auf MediathekViewWeb mit Episode-Matching"""
        try:
            logger.info(f"  Caching: {show_name} (TVDB {tvdb_id})")

            # Check if Sonarr is configured - if not, skip caching entirely
            sonarr_url_config = db.query(Config).filter_by(key="sonarr_url").first()
            sonarr_api_config = db.query(Config).filter_by(key="sonarr_api_key").first()

            if not (sonarr_url_config and sonarr_api_config and sonarr_url_config.value and sonarr_api_config.value):
                logger.info(f"  Skipping {show_name} - Sonarr not configured")
                return 0

            # Step 1: Hole TVDB Episodes (fetch if missing)
            tvdb_cache_entries = db.query(TVDBCache).filter(
                TVDBCache.tvdb_id == tvdb_id
            ).all()

            if not tvdb_cache_entries:
                logger.info(f"  No TVDB cache for {tvdb_id}, fetching from TVDB...")
                # Try to fetch TVDB data
                tvdb_api_config = db.query(Config).filter_by(key="tvdb_api_key").first()
                if tvdb_api_config and tvdb_api_config.value:
                    from app.services.tvdb_client import TVDBClient
                    tvdb_client = TVDBClient(tvdb_api_config.value, db)
                    await tvdb_client.get_episodes(int(tvdb_id), cache_to_db=True)
                    logger.info(f"  ✓ Fetched TVDB data for {show_name}")

                    # Re-query cache after fetching
                    tvdb_cache_entries = db.query(TVDBCache).filter(
                        TVDBCache.tvdb_id == tvdb_id
                    ).all()
                else:
                    logger.warning(f"  TVDB API key not configured, cannot fetch data for {tvdb_id}")
                    return 0

            if not tvdb_cache_entries:
                logger.warning(f"  Still no TVDB cache for {tvdb_id} after fetch attempt")
                return 0
            
            # Convert zu dict format für Matcher
            tvdb_episodes = []
            seasons_found = set()
            for cache in tvdb_cache_entries:
                tvdb_episodes.append({
                    'season': cache.season,
                    'episode': cache.episode,
                    'name': cache.episode_name,
                    'aired': cache.aired_date.isoformat() if cache.aired_date else None,
                    'overview': cache.description or ''
                })
                seasons_found.add(cache.season)

            logger.debug(f"  Loaded {len(tvdb_episodes)} TVDB episodes from seasons: {sorted(seasons_found)}")

            # Debug: Show sample episodes with air dates
            if tvdb_episodes:
                logger.debug("  Sample TVDB episodes:")
                for i, ep in enumerate(tvdb_episodes[:5]):  # Show first 5
                    logger.debug(f"    S{ep['season']:02d}E{ep['episode']:02d} - {ep['name']} - Air: {ep['aired']}")
                if len(tvdb_episodes) > 5:
                    logger.debug(f"    ... and {len(tvdb_episodes) - 5} more episodes")
            
            # Step 2: Lade Filter-Einstellungen aus WatchList
            watchlist_entry = db.query(WatchList).filter(WatchList.tvdb_id == tvdb_id).first()

            # Default-Werte verwenden falls keine Filter gesetzt
            min_duration = watchlist_entry.min_duration if watchlist_entry and watchlist_entry.min_duration else 0
            max_duration = watchlist_entry.max_duration if watchlist_entry and watchlist_entry.max_duration else 360
            exclude_keywords = watchlist_entry.exclude_keywords if watchlist_entry and watchlist_entry.exclude_keywords else "klare Sprache,Audiodeskription,Gebärdensprache"
            include_senders = watchlist_entry.include_senders if watchlist_entry and watchlist_entry.include_senders else ""

            # Step 3: Hole alle Titel-Varianten von TVDB (primary + alternate titles)
            tvdb_api_config = db.query(Config).filter_by(key="tvdb_api_key").first()
            show_titles = [show_name]  # Fallback: mindestens der ursprüngliche Titel

            if tvdb_api_config and tvdb_api_config.value:
                try:
                    from app.services.tvdb_client import TVDBClient
                    tvdb_client = TVDBClient(tvdb_api_config.value)
                    show_titles = await tvdb_client.get_show_titles(int(tvdb_id))
                    if not show_titles:
                        show_titles = [show_name]  # Fallback
                except Exception as e:
                    logger.warning(f"  Failed to get alternate titles from TVDB: {e}")
                    show_titles = [show_name]  # Fallback

            # Step 3.1: Fallback - Hole Titel aus Sonarr falls verfügbar
            if watchlist_entry and watchlist_entry.sonarr_series_id:
                try:
                    sonarr_url_config = db.query(Config).filter_by(key="sonarr_url").first()
                    sonarr_api_config = db.query(Config).filter_by(key="sonarr_api_key").first()

                    if sonarr_url_config and sonarr_api_config and sonarr_url_config.value and sonarr_api_config.value:
                        from app.services.sonarr_webhook import SonarrWebhookManager
                        sonarr_manager = SonarrWebhookManager(sonarr_url_config.value, sonarr_api_config.value)
                        series_info = await sonarr_manager.get_series_info(watchlist_entry.sonarr_series_id)

                        if series_info:
                            sonarr_title = series_info.get("title")
                            if sonarr_title and sonarr_title not in show_titles:
                                show_titles.append(sonarr_title)
                                logger.info(f"  ✓ Added Sonarr title: {sonarr_title}")

                            # Auch alternativen Titel aus Sonarr prüfen
                            alternates = series_info.get("alternateTitles", [])
                            for alt in alternates:
                                alt_title = alt.get("title")
                                if alt_title and alt_title not in show_titles:
                                    show_titles.append(alt_title)
                                    logger.info(f"  ✓ Added Sonarr alternate title: {alt_title}")

                except Exception as e:
                    logger.debug(f"  Failed to get titles from Sonarr: {e}")

            logger.info(f"  Searching with {len(show_titles)} title variants: {show_titles}")

            # Step 4: Suche für jeden Titel-Variante in MediathekViewWeb
            all_mediathek_results = []

            for search_title in show_titles:
                logger.info(f"  🔍 Searching Mediathek for: '{search_title}'")

                # Konstruiere MediathekViewWeb Query dynamisch
                # NUR INKLUSIVE Filter in die URL einbauen (MediathekViewWeb unterstützt keine komplexen Text-Filter)
                query_parts = []

                # Serienname (direkt ohne manuelles Encoding)
                query_parts.append(search_title)

                # Duration Filter in URL (auch wenn sie nicht funktionieren - für Debugging)
                if min_duration > 0 or max_duration < 360:
                    query_parts.append(f">{min_duration} <{max_duration}")

                # Sender Filter: !ard !zdf !3sat (aus include_senders, leer=alle)
                if include_senders and include_senders.strip():
                    senders = [s.strip() for s in include_senders.split(',') if s.strip()]
                    for sender in senders:
                        query_parts.append(f"!{sender}")

                # KEINE exclude_keywords in der URL! Diese werden später im Matcher gefiltert

                # Konstruiere finale Query
                query = " ".join(query_parts)
                # URL-kodiere die Query für die URL (nur einmal!)
                from urllib.parse import quote
                encoded_query = quote(query)
                feed_url = f"https://mediathekviewweb.de/feed?query={encoded_query}&future=false"

                # Logge die finale Query und alle verwendeten Filter
                logger.info(f"    MediathekViewWeb Query: {query}")
                logger.info(f"    MediathekViewWeb URL: {feed_url}")

                mediathek_results = []
                async with create_aiohttp_session() as session:
                    try:
                        async with session.get(feed_url, timeout=15) as resp:
                            if resp.status != 200:
                                logger.warning(f"    Feed failed: {resp.status}")
                                continue

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
                                    'searched_with': search_title  # Markiere mit welchem Titel gesucht wurde
                                })
                    except Exception as e:
                        logger.warning(f"    Feed fetch error for '{search_title}': {e}")
                        continue

                logger.info(f"    Found {len(mediathek_results)} results for '{search_title}'")
                all_mediathek_results.extend(mediathek_results)

            # Entferne Duplikate (gleiche Links)
            unique_results = []
            seen_links = set()
            for result in all_mediathek_results:
                if result['link'] not in seen_links:
                    unique_results.append(result)
                    seen_links.add(result['link'])

            mediathek_results = unique_results
            logger.info(f"  Total unique Mediathek results: {len(mediathek_results)} (from {len(show_titles)} title variants)")
            logger.info(f"  Filter - Duration: >{min_duration}<{max_duration}, Senders: '{include_senders}', Exclude: '{exclude_keywords}' (filtered in matcher)")
            
            if not mediathek_results:
                logger.info(f"  No results for {show_name}")
                return 0

            logger.debug(f"  Found {len(mediathek_results)} Mediathek results before filtering")

            # Step 3.5: Apply Duration Filter in code (since URL filters don't work properly)
            if min_duration > 0 or max_duration < 360:
                filtered_results = []
                for ep in mediathek_results:
                    # Try to extract duration from title or description
                    duration = self._extract_duration_from_episode(ep)
                    if duration is not None:
                        if duration >= min_duration and duration <= max_duration:
                            filtered_results.append(ep)
                        else:
                            logger.debug(f"  Episode filtered by duration {duration}min: {ep.get('title', '')}")
                    else:
                        # If no duration found, include episode (assume it meets criteria)
                        filtered_results.append(ep)

                mediathek_results = filtered_results
                logger.debug(f"  After duration filtering: {len(mediathek_results)} Mediathek results")
            
            # Step 3: Match mit Matcher
            matcher = EpisodeMatcher(db)
            cached = 0
            
            for mvw_ep in mediathek_results:
                # Prüfe zuerst exclude_keywords Filter (ohne Match-Logs)
                if matcher.filter_excluded_keywords(mvw_ep, exclude_keywords):
                    # Episode ist NICHT gefiltert - normale Verarbeitung
                    match_result = matcher.match_episode(mvw_ep, tvdb_episodes, exclude_keywords)

                    if match_result:
                        # Prüfe Download-Entscheidung
                        download_decision = await self._decide_download_action(match_result.season, match_result.episode, watchlist_entry, db)

                        # Prüfe ob bereits im Cache
                        existing = db.query(MediathekCache).filter(
                            MediathekCache.tvdb_id == tvdb_id,
                            MediathekCache.season == match_result.season,
                            MediathekCache.episode == match_result.episode,
                            MediathekCache.expires_at > datetime.utcnow()
                        ).first()

                        if existing:
                            continue  # Bereits gecached - nichts zu tun

                        cache_entry = None  # Initialize cache_entry

                        if download_decision == "download":
                            logger.info(f"  → downloading episode")
                            # Erstelle Cache-Eintrag für Download
                            cache_entry = MediathekCache(
                                tvdb_id=tvdb_id,
                                season=match_result.season,
                                episode=match_result.episode,
                                episode_title=match_result.episode_title or mvw_ep['title'],
                                mediathek_title=mvw_ep['title'],
                                mediathek_platform="ard",
                                media_url=mvw_ep['link'],
                                quality=self._guess_quality(mvw_ep['title']),
                                match_confidence=int(match_result.confidence * 100),  # 0-100
                                match_type=match_result.match_type,
                                expires_at=datetime.utcnow() + timedelta(days=self.CACHE_DURATION_DAYS)
                            )
                            # Download the episode immediately
                            success = await self._download_episode_to_sonarr_path(
                                cache_entry, match_result.season, match_result.episode, watchlist_entry.sonarr_series_id, db
                            )
                            if success:
                                logger.info(f"    ✓ Downloaded S{match_result.season:02d}E{match_result.episode:02d} for {show_name}")
                            else:
                                logger.warning(f"    ✗ Failed to download S{match_result.season:02d}E{match_result.episode:02d} for {show_name}")
                        elif download_decision == "file_exists":
                            logger.info(f"  → ignoring, file already exists")
                            continue  # Nicht cachen wenn Datei bereits existiert
                        elif download_decision == "not_monitored":
                            logger.info(f"  → ignoring, episode not monitored in Sonarr")
                            continue  # Nicht cachen wenn nicht monitored
                        else:
                            logger.info(f"  → caching episode for future use")
                            # Erstelle Cache-Eintrag für spätere Verwendung
                            cache_entry = MediathekCache(
                                tvdb_id=tvdb_id,
                                season=match_result.season,
                                episode=match_result.episode,
                                episode_title=match_result.episode_title or mvw_ep['title'],
                                mediathek_title=mvw_ep['title'],
                                mediathek_platform="ard",
                                media_url=mvw_ep['link'],
                                quality=self._guess_quality(mvw_ep['title']),
                                match_confidence=int(match_result.confidence * 100),  # 0-100
                                match_type=match_result.match_type,
                                expires_at=datetime.utcnow() + timedelta(days=self.CACHE_DURATION_DAYS)
                            )

                        # Cache-Eintrag zur Datenbank hinzufügen (nur wenn erstellt)
                        if cache_entry is not None:
                            db.add(cache_entry)
                            cached += 1
                            logger.debug(f"  Cache entry created, total cached: {cached}")
                # else: Episode wurde gefiltert - nur die Filter-Nachricht vom Matcher wird angezeigt
            
            # AUTOMATISCHES TAGGING ENTFERNT: Nur manuell getaggte Serien werden verarbeitet

            # SMART AUTO-DOWNLOAD: Check for missing episodes and download them
            if watchlist_entry and watchlist_entry.sonarr_series_id:
                try:
                    await self._sync_monitored_episodes(db, watchlist_entry, show_name)
                except Exception as e:
                    logger.error(f"  Error during smart auto-download for {show_name}: {e}")

            if cached > 0:
                db.commit()
                logger.info(f"  ✅ Cached {cached} new episodes")

                # Update episodes_found count and mediathek_episodes_count
                if watchlist_entry:
                    watchlist_entry.episodes_found += cached
                    # Update total mediathek episodes count for this series
                    total_episodes = db.query(MediathekCache).filter(
                        MediathekCache.tvdb_id == tvdb_id,
                        MediathekCache.expires_at > datetime.utcnow()
                    ).count()
                    watchlist_entry.mediathek_episodes_count = total_episodes
                    db.commit()
            else:
                # Even if no new episodes were cached, update mediathek_episodes_count
                if watchlist_entry:
                    total_episodes = db.query(MediathekCache).filter(
                        MediathekCache.tvdb_id == tvdb_id,
                        MediathekCache.expires_at > datetime.utcnow()
                    ).count()
                    watchlist_entry.mediathek_episodes_count = total_episodes
                    db.commit()

            return cached
        
        except Exception as e:
            logger.error(f"  Cache error for {show_name}: {e}", exc_info=True)
            return 0
    
    def _extract_duration_from_episode(self, mediathek_episode: dict) -> Optional[int]:
        """
        Extract duration in minutes from episode title or description.
        Returns None if no duration found.
        """
        import re

        title = mediathek_episode.get('title', '').lower()
        description = mediathek_episode.get('description', '').lower()

        # Patterns to match duration: "90 min", "90 Minuten", "90min", "1:30:00" (but convert to minutes)
        patterns = [
            r'(\d+)\s*min',           # "90 min"
            r'(\d+)\s*Minuten',       # "90 Minuten"
            r'(\d+)min\b',            # "90min"
            r'(\d+):(\d+):(\d+)',     # "1:30:00" (hours:minutes:seconds)
            r'(\d+):(\d+)',           # "90:00" (minutes:seconds, assume hours:minutes)
        ]

        text_to_search = f"{title} {description}"

        for pattern in patterns:
            matches = re.findall(pattern, text_to_search)
            if matches:
                if len(matches[0]) == 1:  # Single number (minutes)
                    return int(matches[0])
                elif len(matches[0]) == 2:  # hours:minutes
                    hours, minutes = map(int, matches[0])
                    return hours * 60 + minutes
                elif len(matches[0]) == 3:  # hours:minutes:seconds
                    hours, minutes, seconds = map(int, matches[0])
                    return hours * 60 + minutes + (seconds // 60)  # Round seconds to minutes

        return None

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
    
    async def _sync_monitored_episodes(self, db: Session, watchlist_entry: WatchList, show_name: str):
        """
        Smart auto-download: Check Sonarr for monitored episodes without files
        and download them if available in mediathek
        """
        try:
            # Get Sonarr config
            sonarr_url_config = db.query(Config).filter_by(key="sonarr_url").first()
            sonarr_api_config = db.query(Config).filter_by(key="sonarr_api_key").first()

            if not (sonarr_url_config and sonarr_api_config and sonarr_url_config.value and sonarr_api_config.value):
                logger.debug("Sonarr not configured, skipping smart download")
                return

            sonarr_manager = SonarrWebhookManager(sonarr_url_config.value, sonarr_api_config.value)
            download_path = PBARR_DOWNLOAD_PATH

            # Get monitored episodes from Sonarr that don't have files
            monitored_episodes = await sonarr_manager.get_monitored_episodes_without_files(
                watchlist_entry.sonarr_series_id
            )

            if not monitored_episodes:
                logger.debug(f"No monitored episodes without files for {show_name}")
                return

            logger.info(f"  Found {len(monitored_episodes)} monitored episodes without files for {show_name}")

            # Get available mediathek episodes
            mediathek_episodes = db.query(MediathekCache).filter(
                MediathekCache.tvdb_id == watchlist_entry.tvdb_id,
                MediathekCache.expires_at > datetime.utcnow()
            ).all()

            logger.info(f"  Found {len(mediathek_episodes)} cached mediathek episodes for {show_name}")

            downloaded_count = 0

            for sonarr_ep in monitored_episodes:
                season = sonarr_ep.get("seasonNumber")
                episode = sonarr_ep.get("episodeNumber")

                logger.debug(f"  Checking S{season:02d}E{episode:02d} for {show_name}")

                # Check if available in mediathek
                mediathek_match = next(
                    (m for m in mediathek_episodes
                     if m.season == season and m.episode == episode),
                    None
                )

                if mediathek_match:
                    logger.info(f"  Found mediathek match for S{season:02d}E{episode:02d}, downloading...")
                    logger.debug(f"  Mediathek match details: {mediathek_match.media_url}, series_id: {watchlist_entry.sonarr_series_id}")
                    # Download the episode
                    success = await self._download_episode_to_sonarr_path(
                        mediathek_match, season, episode, watchlist_entry.sonarr_series_id, db
                    )
                    if success:
                        downloaded_count += 1
                        logger.info(f"    ✓ Downloaded S{season:02d}E{episode:02d} for {show_name}")
                    else:
                        logger.warning(f"    ✗ Failed to download S{season:02d}E{episode:02d} for {show_name}")
                else:
                    logger.debug(f"  No mediathek match found for S{season:02d}E{episode:02d}")

            if downloaded_count > 0:
                logger.info(f"  📥 Downloaded {downloaded_count} episodes for {show_name}")

                # Trigger Sonarr series rescan for the downloaded files
                try:
                    sonarr_url_config = db.query(Config).filter_by(key="sonarr_url").first()
                    sonarr_api_config = db.query(Config).filter_by(key="sonarr_api_key").first()

                    if sonarr_url_config and sonarr_api_config and sonarr_url_config.value and sonarr_api_config.value:
                        sonarr_manager = SonarrWebhookManager(sonarr_url_config.value, sonarr_api_config.value)
                        rescan_result = await sonarr_manager.rescan_series(watchlist_entry.sonarr_series_id)
                        if rescan_result.get("success"):
                            logger.info(f"  ✅ Triggered Sonarr series rescan for {downloaded_count} episodes")
                        else:
                            logger.warning(f"  Failed to trigger series rescan: {rescan_result.get('message')}")
                    else:
                        logger.debug("  Sonarr not configured, skipping series rescan")
                except Exception as e:
                    logger.error(f"  Error triggering series rescan: {e}")

        except Exception as e:
            logger.error(f"Error in smart auto-download for {show_name}: {e}", exc_info=True)

    async def _detect_monitoring_changes(self, db: Session):
        """
        Smart Monitoring Detection: Check if user changed monitored episodes in Sonarr
        and trigger immediate downloads for newly monitored episodes
        """
        try:
            logger.info("🔍 Checking for episode monitoring changes...")

            # Get all series with sonarr_series_id
            watchlist_entries = db.query(WatchList).filter(
                WatchList.sonarr_series_id.isnot(None)
            ).all()

            if not watchlist_entries:
                logger.debug("No series with Sonarr integration found")
                return

            # Get Sonarr config
            sonarr_url_config = db.query(Config).filter_by(key="sonarr_url").first()
            sonarr_api_config = db.query(Config).filter_by(key="sonarr_api_key").first()

            if not (sonarr_url_config and sonarr_api_config and sonarr_url_config.value and sonarr_api_config.value):
                logger.debug("Sonarr not configured, skipping monitoring detection")
                return

            sonarr_manager = SonarrWebhookManager(sonarr_url_config.value, sonarr_api_config.value)

            changes_detected = 0

            for watchlist_entry in watchlist_entries:
                try:
                    # Check for monitoring changes in this series
                    changed, new_monitored = await self._check_series_monitoring_changes(
                        sonarr_manager, watchlist_entry, db
                    )

                    if changed:
                        logger.info(f"📡 Monitoring changes detected for {watchlist_entry.show_name}")
                        changes_detected += 1

                        # Handle the monitoring change - trigger immediate download
                        await self._handle_monitoring_change(watchlist_entry, new_monitored, db)

                        # Update stored state
                        await self._update_monitoring_state(watchlist_entry.sonarr_series_id, new_monitored, db)

                except Exception as e:
                    logger.error(f"Error checking monitoring changes for {watchlist_entry.show_name}: {e}")

            if changes_detected > 0:
                logger.info(f"✅ Detected monitoring changes in {changes_detected} series")
            else:
                logger.debug("No monitoring changes detected")

        except Exception as e:
            logger.error(f"Error in monitoring detection: {e}", exc_info=True)

    async def _check_series_monitoring_changes(self, sonarr_manager: SonarrWebhookManager, watchlist_entry: WatchList, db: Session):
        """
        Check if monitored episodes changed for a specific series

        Returns: (changed: bool, current_missing_episodes: List[dict])
        """
        try:
            # Get current monitored episodes WITHOUT files (Sonarr is MISSING these)
            current_missing_episodes = await sonarr_manager.get_monitored_episodes_without_files(
                watchlist_entry.sonarr_series_id
            )

            # Get stored monitoring state (episodes that were previously missing)
            stored_states = db.query(EpisodeMonitoringState).filter_by(
                sonarr_series_id=watchlist_entry.sonarr_series_id
            ).all()

            # Convert to comparable format
            current_set = {(ep.get("seasonNumber"), ep.get("episodeNumber")) for ep in current_missing_episodes}
            stored_set = {(state.season, state.episode) for state in stored_states}

            # Check if there are differences (new episodes became monitored/missing)
            if current_set != stored_set:
                return True, current_missing_episodes
            else:
                return False, None

        except Exception as e:
            logger.error(f"Error checking monitoring changes for series {watchlist_entry.sonarr_series_id}: {e}")
            return False, None

    async def _handle_monitoring_change(self, watchlist_entry: WatchList, new_monitored_episodes: list, db: Session):
        """
        Handle monitoring change: Trigger immediate download for newly monitored episodes
        """
        try:
            logger.info(f"🎯 Handling monitoring change for {watchlist_entry.show_name}")

            # Force refresh mediathek cache for this series
            await self._force_refresh_mediathek_cache(watchlist_entry.tvdb_id, watchlist_entry.show_name, db)

            # Trigger smart download with force flag
            await self._sync_monitored_episodes_force(db, watchlist_entry, watchlist_entry.show_name)

        except Exception as e:
            logger.error(f"Error handling monitoring change for {watchlist_entry.show_name}: {e}")

    async def _force_refresh_mediathek_cache(self, tvdb_id: str, show_name: str, db: Session):
        """
        Force refresh mediathek cache for a series (ignore existing cache)
        """
        try:
            logger.debug(f"🔄 Force refreshing mediathek cache for {show_name}")

            # Get TVDB episodes
            tvdb_cache_entries = db.query(TVDBCache).filter(TVDBCache.tvdb_id == tvdb_id).all()
            if not tvdb_cache_entries:
                return

            tvdb_episodes = []
            for cache in tvdb_cache_entries:
                tvdb_episodes.append({
                    'season': cache.season,
                    'episode': cache.episode,
                    'name': cache.episode_name,
                    'aired': cache.aired_date.isoformat() if cache.aired_date else None,
                    'overview': cache.description or ''
                })

            # Lade Filter-Einstellungen aus WatchList für dynamische Query
            watchlist_entry = db.query(WatchList).filter(WatchList.tvdb_id == tvdb_id).first()

            # Default-Werte verwenden falls keine Filter gesetzt
            min_duration = watchlist_entry.min_duration if watchlist_entry and watchlist_entry.min_duration else 0
            max_duration = watchlist_entry.max_duration if watchlist_entry and watchlist_entry.max_duration else 360
            exclude_keywords = watchlist_entry.exclude_keywords if watchlist_entry and watchlist_entry.exclude_keywords else "klare Sprache,Audiodeskription,Gebärdensprache"
            include_senders = watchlist_entry.include_senders if watchlist_entry and watchlist_entry.include_senders else ""

            # Konstruiere MediathekViewWeb Query dynamisch
            # NUR INKLUSIVE Filter in die URL einbauen (MediathekViewWeb unterstützt keine komplexen Text-Filter)
            query_parts = []

            # Serienname (direkt ohne manuelles Encoding)
            query_parts.append(show_name)

            # Duration Filter in URL (auch wenn sie nicht funktionieren - für Debugging)
            if min_duration > 0 or max_duration < 360:
                query_parts.append(f">{min_duration} <{max_duration}")

            # Sender Filter: !ard !zdf !3sat (aus include_senders, leer=alle)
            if include_senders and include_senders.strip():
                senders = [s.strip() for s in include_senders.split(',') if s.strip()]
                for sender in senders:
                    query_parts.append(f"!{sender}")

            # KEINE exclude_keywords in der URL! Diese werden später im Matcher gefiltert

            # Konstruiere finale Query
            query = " ".join(query_parts)
            # URL-kodiere die Query für die URL (nur einmal!)
            from urllib.parse import quote
            encoded_query = quote(query)
            feed_url = f"https://mediathekviewweb.de/feed?query={encoded_query}&future=false"

            logger.info(f"  Force refresh MediathekViewWeb Query: {query}")
            logger.info(f"  Filter - Duration: >{min_duration}<{max_duration}, Senders: '{include_senders}', Exclude: '{exclude_keywords}' (filtered in matcher)")

            mediathek_results = []
            async with create_aiohttp_session() as session:
                async with session.get(feed_url, timeout=15) as resp:
                    if resp.status == 200:
                        content = await resp.text()
                        root = ET.fromstring(content)

                        for item in root.findall('.//item'):
                            title = item.findtext('title', '')
                            link = item.findtext('link', '')
                            if link:
                                mediathek_results.append({
                                    'title': title,
                                    'link': link,
                                    'pub_date': item.findtext('pubDate', ''),
                                    'description': item.findtext('description', ''),
                                })

            # Match and cache (force update existing)
            matcher = EpisodeMatcher(db)
            cached = 0

            for mvw_ep in mediathek_results:
                match_result = matcher.match_episode(mvw_ep, tvdb_episodes, exclude_keywords)
                if not match_result:
                    continue

                # Always update/create cache entry (force refresh)
                existing = db.query(MediathekCache).filter(
                    MediathekCache.tvdb_id == tvdb_id,
                    MediathekCache.season == match_result.season,
                    MediathekCache.episode == match_result.episode
                ).first()

                if existing:
                    # Update existing
                    existing.episode_title = mvw_ep['title']
                    existing.media_url = mvw_ep['link']
                    existing.quality = self._guess_quality(mvw_ep['title'])
                    existing.match_confidence = int(match_result.confidence * 100)
                    existing.match_type = match_result.match_type
                    existing.expires_at = datetime.utcnow() + timedelta(days=self.CACHE_DURATION_DAYS)
                else:
                    # Create new
                    cache_entry = MediathekCache(
                        tvdb_id=tvdb_id,
                        season=match_result.season,
                        episode=match_result.episode,
                        episode_title=mvw_ep['title'],
                        mediathek_title=mvw_ep['title'],
                        mediathek_platform="ard",
                        media_url=mvw_ep['link'],
                        quality=self._guess_quality(mvw_ep['title']),
                        match_confidence=int(match_result.confidence * 100),
                        match_type=match_result.match_type,
                        expires_at=datetime.utcnow() + timedelta(days=self.CACHE_DURATION_DAYS)
                    )
                    db.add(cache_entry)

                cached += 1

            if cached > 0:
                db.commit()
                logger.info(f"  🔄 Force refreshed {cached} mediathek episodes for {show_name}")

        except Exception as e:
            logger.error(f"Error force refreshing mediathek cache for {show_name}: {e}")

    async def _sync_monitored_episodes_force(self, db: Session, watchlist_entry: WatchList, show_name: str):
        """
        Force sync monitored episodes (ignore cache timeouts)
        """
        try:
            download_path = PBARR_DOWNLOAD_PATH

            # Get ALL monitored episodes from Sonarr (not just without files)
            sonarr_url_config = db.query(Config).filter_by(key="sonarr_url").first()
            sonarr_api_config = db.query(Config).filter_by(key="sonarr_api_key").first()

            if not (sonarr_url_config and sonarr_api_config):
                return

            sonarr_manager = SonarrWebhookManager(sonarr_url_config.value, sonarr_api_config.value)

            # Get all episodes for this series
            async with create_httpx_client(timeout=10.0) as client:
                resp = await client.get(
                    f"{sonarr_manager.url}/api/v3/episode?seriesId={watchlist_entry.sonarr_series_id}",
                    headers=sonarr_manager.headers
                )

                if resp.status_code != 200:
                    return

                all_episodes = resp.json()
                monitored_episodes = [ep for ep in all_episodes if ep.get("monitored")]

            # Get available mediathek episodes (fresh)
            mediathek_episodes = db.query(MediathekCache).filter(
                MediathekCache.tvdb_id == watchlist_entry.tvdb_id,
                MediathekCache.expires_at > datetime.utcnow()
            ).all()

            downloaded_count = 0

            for sonarr_ep in monitored_episodes:
                season = sonarr_ep.get("seasonNumber")
                episode = sonarr_ep.get("episodeNumber")

                # Check if available in mediathek
                mediathek_match = next(
                    (m for m in mediathek_episodes
                     if m.season == season and m.episode == episode),
                    None
                )

                if mediathek_match:
                    # Download the episode
                    success = await self._download_episode_to_sonarr_path(
                        mediathek_match, season, episode, watchlist_entry.sonarr_series_id, db
                    )
                    if success:
                        downloaded_count += 1
                        logger.info(f"    🚀 Downloaded S{season:02d}E{episode:02d} for {show_name} (monitoring change)")
                    else:
                        logger.warning(f"    ✗ Failed to download S{season:02d}E{episode:02d} for {show_name}")

            if downloaded_count > 0:
                logger.info(f"  📥 Downloaded {downloaded_count} episodes for {show_name} due to monitoring changes")

        except Exception as e:
            logger.error(f"Error in force sync monitored episodes for {show_name}: {e}")

    async def _update_monitoring_state(self, sonarr_series_id: int, monitored_episodes: list, db: Session):
        """
        Update the stored monitoring state for a series
        """
        try:
            # Delete old state
            db.query(EpisodeMonitoringState).filter_by(
                sonarr_series_id=sonarr_series_id
            ).delete()

            # Insert new state
            for ep in monitored_episodes:
                state = EpisodeMonitoringState(
                    sonarr_series_id=sonarr_series_id,
                    season=ep.get("seasonNumber"),
                    episode=ep.get("episodeNumber"),
                    monitored=True,
                    checked_at=datetime.utcnow()
                )
                db.add(state)

            db.commit()
            logger.debug(f"Updated monitoring state for series {sonarr_series_id}")

        except Exception as e:
            logger.error(f"Error updating monitoring state for series {sonarr_series_id}: {e}")

    def _sanitize_filename(self, text: str) -> str:
        """
        Sanitize text for use in filenames:
        - Convert German umlauts (ö→oe, ä→ae, ü→ue, ß→ss)
        - Remove special characters like ?!
        - Replace problematic characters with safe alternatives
        """
        if not text:
            return ""

        # Convert German umlauts
        text = text.replace('ä', 'ae').replace('Ä', 'Ae')
        text = text.replace('ö', 'oe').replace('Ö', 'Oe')
        text = text.replace('ü', 'ue').replace('Ü', 'Ue')
        text = text.replace('ß', 'ss')

        # Remove special characters
        text = text.replace('?', '').replace('!', '').replace('(', '').replace(')', '').replace('[', '').replace(']', '')

        # Replace other problematic characters with spaces
        text = text.replace('/', ' ').replace('\\', ' ').replace(':', ' ').replace('*', '').replace('"', '').replace('<', '').replace('>', '').replace('|', ' ')
        text = text.replace(',', '').replace(';', '').replace('=', '').replace('+', '').replace('@', '').replace('#', '').replace('$', '').replace('%', '').replace('&', ' and ')
        # Also replace existing dashes with spaces
        text = text.replace('-', ' ')

        # Replace multiple spaces with single spaces, keep spaces instead of dashes
        import re
        text = re.sub(r'\s+', ' ', text.strip())

        return text

    def _normalize_filename(self, text: str) -> str:
        """
        Normalize filename: Remove special characters, keep alphanumeric and spaces
        """
        if not text:
            return ""

        import re
        # Remove dashes, special chars, but keep letters/numbers/spaces
        normalized = re.sub(r'[^a-zA-Z0-9\s]', '', text).strip()
        # Remove extra spaces
        normalized = re.sub(r'\s+', ' ', normalized)
        return normalized

    async def _get_series_structure(self, sonarr_series_path: str, season: int, sonarr_series_id: int, db: Session) -> str:
        """
        Determine the correct folder structure for a series using Sonarr's seasonFolder setting
        Maps from Sonarr's path (/tv/...) to PBArr's library path (/app/library/...)
        Returns the correct target folder in PBArr's library
        """
        from pathlib import Path

        # Extract series folder name from Sonarr's path
        series_folder_name = Path(sonarr_series_path).name

        # Map to PBArr's library path
        library_root = Path("/app/library")
        mapped_series_path = library_root / series_folder_name

        # Get Sonarr config to check seasonFolder setting
        sonarr_url_config = db.query(Config).filter_by(key="sonarr_url").first()
        sonarr_api_config = db.query(Config).filter_by(key="sonarr_api_key").first()

        if sonarr_url_config and sonarr_api_config and sonarr_url_config.value and sonarr_api_config.value:
            try:
                sonarr_manager = SonarrWebhookManager(sonarr_url_config.value, sonarr_api_config.value)
                season_folder_setting = await sonarr_manager.get_series_season_folder_setting(sonarr_series_id)

                if season_folder_setting is True:
                    # Series uses season folders
                    season_folder = mapped_series_path / f"Season {season:02d}"
                    logger.info(f"Series uses Season folders (from Sonarr API): {season_folder}")
                    return str(season_folder)
                elif season_folder_setting is False:
                    # Series uses flat structure
                    logger.info(f"Series is flat (from Sonarr API): {mapped_series_path}")
                    return str(mapped_series_path)
                else:
                    logger.warning(f"Could not determine season folder setting from Sonarr API, falling back to file system check")
            except Exception as e:
                logger.error(f"Error getting season folder setting from Sonarr API: {e}, falling back to file system check")

        # Fallback: Check file system if Sonarr API is not available or failed
        season_folder = mapped_series_path / f"Season {season:02d}"

        if season_folder.exists():
            logger.info(f"Series uses Season folders (fallback file system check): {season_folder}")
            return str(season_folder)
        else:
            logger.info(f"Series is flat (fallback file system check): {mapped_series_path}")
            return str(mapped_series_path)

    async def _download_episode_to_sonarr_path(
        self,
        mediathek_entry,
        season: int,
        episode: int,
        sonarr_series_id: int,
        db: Session
    ):
        """Download episode directly to Sonarr library"""
        try:
            logger.debug(f"Starting download for S{season:02d}E{episode:02d}, series_id: {sonarr_series_id}")

            # Step 1: Get series info
            sonarr_url_config = db.query(Config).filter_by(key="sonarr_url").first()
            sonarr_api_config = db.query(Config).filter_by(key="sonarr_api_key").first()

            logger.debug(f"Sonarr URL config: {sonarr_url_config.value if sonarr_url_config else 'None'}")
            logger.debug(f"Sonarr API config: {'***' if sonarr_api_config and sonarr_api_config.value else 'None'}")

            if not sonarr_url_config or not sonarr_api_config or not sonarr_url_config.value or not sonarr_api_config.value:
                logger.error("Sonarr config not available")
                return False

            logger.debug(f"Creating SonarrWebhookManager with URL: {sonarr_url_config.value}")
            sonarr_manager = SonarrWebhookManager(sonarr_url_config.value, sonarr_api_config.value)
            logger.debug(f"Getting series info for series_id: {sonarr_series_id}")
            series = await sonarr_manager.get_series_info(sonarr_series_id)
            logger.debug(f"Series info result: {series}")

            if not series:
                logger.error(f"Series {sonarr_series_id} not found")
                return False

            series_title = series["title"]
            sonarr_series_path = series["path"]  # e.g., "/tv/Show Name" or "/tv/Show Name/Season 01"
            logger.debug(f"Series title: {series_title}, path: {sonarr_series_path}")

            # Download the episode (minimal logging)
            try:
                # Get target folder
                target_folder = await self._get_series_structure(sonarr_series_path, season, sonarr_series_id, db)

                # Get episode info and build filename
                episode_data = await sonarr_manager.get_episode(sonarr_series_id, season, episode)
                episode_title = episode_data.get("title", "Unknown")

                from app.utils.filename import normalize_filename
                series_title_normalized = normalize_filename(series_title)
                episode_title_normalized = normalize_filename(episode_title)
                filename = f"{series_title_normalized} - S{season:02d}E{episode:02d} - {episode_title_normalized}.mkv"

                # Download to temp location
                temp_dir = Path("/tmp/pbarr_downloads")
                temp_dir.mkdir(exist_ok=True)
                temp_file = temp_dir / filename

                # Download with curl (direct MP4 links from Mediathek)
                cmd = [
                    'curl',
                    '-L',  # Follow redirects
                    '-s',  # Silent mode
                    '-o', str(temp_file),  # Output file
                    '--max-time', '1800',  # 30 minutes timeout
                    '--retry', '3',  # Retry 3 times
                    '--retry-delay', '5',  # Wait 5 seconds between retries
                    mediathek_entry.media_url
                ]

                logger.debug(f"Downloading with curl: {mediathek_entry.media_url}")
                result = await asyncio.to_thread(
                    subprocess.run,
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=1800  # 30 minutes timeout
                )

                if result.returncode != 0:
                    error_msg = result.stderr.strip() if result.stderr else "Unknown curl error"
                    logger.warning(f"Curl download failed: {error_msg}")
                    return False

                logger.debug("Curl download successful")

                if not temp_file.exists():
                    logger.error(f"Download failed or temp file doesn't exist")
                    return False

                # Move file to final location
                final_dir = Path(target_folder)
                final_dir.mkdir(parents=True, exist_ok=True)
                final_path = final_dir / filename

                shutil.move(str(temp_file), str(final_path))

                # Trigger Sonarr rescan
                scan_result = await sonarr_manager.trigger_disk_scan(sonarr_series_id)
                if not scan_result.get("success"):
                    logger.warning(f"Failed to trigger rescan: {scan_result.get('message')}")

                return True

            except Exception as e:
                logger.warning(f"Download failed: {str(e)}")
                return False

        except Exception as e:
            logger.error(f"❌ Error in _download_episode_to_sonarr_path: {e}", exc_info=True)
            return False

    async def _decide_download_action(self, season: int, episode: int, watchlist_entry: WatchList, db: Session) -> str:
        """
        Decide what to do with a matched episode
        Returns: "download", "file_exists", "not_monitored", "no_sonarr", "unknown"
        """
        try:
            # Check if Sonarr is configured
            sonarr_url_config = db.query(Config).filter_by(key="sonarr_url").first()
            sonarr_api_config = db.query(Config).filter_by(key="sonarr_api_key").first()

            if not (sonarr_url_config and sonarr_api_config and sonarr_url_config.value and sonarr_api_config.value):
                return "no_sonarr"

            # Check if episode exists in Sonarr and is monitored
            sonarr_manager = SonarrWebhookManager(sonarr_url_config.value, sonarr_api_config.value)

            try:
                episode_data = await sonarr_manager.get_episode(watchlist_entry.sonarr_series_id, season, episode)
                if not episode_data:
                    return "not_monitored"  # Episode doesn't exist in Sonarr

                if not episode_data.get("monitored", False):
                    return "not_monitored"  # Episode exists but is not monitored

                # Check if file already exists
                if episode_data.get("hasFile", False):
                    return "file_exists"

                return "download"

            except Exception as e:
                logger.debug(f"Error checking episode status: {e}")
                return "unknown"

        except Exception as e:
            logger.error(f"Error in _decide_download_action: {e}")
            return "unknown"

    async def cache_series(self, tvdb_id: str, show_name: str):
        """
        Cache a single series (public method for webhook handler)

        Args:
            tvdb_id: TVDB ID of the series
            show_name: Name of the series
        """
        db = SessionLocal()
        try:
            logger.info(f"Starting mediathek caching for single series: {show_name} (TVDB: {tvdb_id})")
            await self._cache_show(tvdb_id, show_name, db)
            logger.info(f"✅ Completed caching for {show_name}")
        except Exception as e:
            logger.error(f"❌ Failed to cache series {show_name}: {e}", exc_info=True)
            raise
        finally:
            db.close()

    async def _cleanup_orphaned_series(self, db: Session):
        """
        Check if watchlist series still exist in Sonarr and have PBArr tag, remove orphaned entries
        from all PBArr tables: watch_list, mediathek_cache, tvdb_cache, episode_monitoring_state
        """
        try:
            logger.info("🔍 Checking for orphaned series in Sonarr...")

            # Get Sonarr config
            sonarr_url_config = db.query(Config).filter_by(key="sonarr_url").first()
            sonarr_api_config = db.query(Config).filter_by(key="sonarr_api_key").first()

            if not (sonarr_url_config and sonarr_api_config and sonarr_url_config.value and sonarr_api_config.value):
                logger.info("Sonarr not configured, skipping orphaned series cleanup")
                return

            sonarr_manager = SonarrWebhookManager(sonarr_url_config.value, sonarr_api_config.value)

            # Get PBArr tag ID for checking
            pbarr_tag_id = await sonarr_manager._get_or_create_pbarr_tag()
            if not pbarr_tag_id:
                logger.warning("Could not get PBArr tag ID, skipping tag validation")
                pbarr_tag_id = None

            # Get all series from watchlist that are tagged in Sonarr
            watchlist_series = db.query(WatchList).filter(
                WatchList.tagged_in_sonarr == True,
                WatchList.sonarr_series_id.isnot(None)
            ).all()

            if not watchlist_series:
                logger.info("No series tagged in Sonarr to check")
                return

            logger.info(f"Checking {len(watchlist_series)} series for existence and PBArr tag in Sonarr...")

            orphaned_count = 0

            for watchlist_entry in watchlist_series:
                try:
                    # Check if series still exists in Sonarr
                    series_info = await sonarr_manager.get_series_info(watchlist_entry.sonarr_series_id)

                    if not series_info:
                        # Series no longer exists in Sonarr - clean up all related data
                        logger.info(f"🗑️ Series '{watchlist_entry.show_name}' (TVDB: {watchlist_entry.tvdb_id}) no longer exists in Sonarr, cleaning up...")

                        # Delete from mediathek_cache
                        mediathek_deleted = db.query(MediathekCache).filter(
                            MediathekCache.tvdb_id == watchlist_entry.tvdb_id
                        ).delete()

                        # Delete from tvdb_cache
                        tvdb_deleted = db.query(TVDBCache).filter(
                            TVDBCache.tvdb_id == watchlist_entry.tvdb_id
                        ).delete()

                        # Delete from episode_monitoring_state
                        monitoring_deleted = db.query(EpisodeMonitoringState).filter(
                            EpisodeMonitoringState.sonarr_series_id == watchlist_entry.sonarr_series_id
                        ).delete()

                        # Delete from watch_list
                        db.delete(watchlist_entry)

                        db.commit()

                        logger.info(f"  ✅ Cleaned up orphaned series '{watchlist_entry.show_name}':")
                        logger.info(f"    - {mediathek_deleted} mediathek cache entries")
                        logger.info(f"    - {tvdb_deleted} TVDB cache entries")
                        logger.info(f"    - {monitoring_deleted} monitoring state entries")
                        logger.info(f"    - 1 watchlist entry")

                        orphaned_count += 1
                    else:
                        # Series exists in Sonarr - check if it still has PBArr tag
                        if pbarr_tag_id:
                            series_tags = series_info.get("tags", [])
                            if pbarr_tag_id not in series_tags:
                                # Series exists but no longer has PBArr tag - clean up
                                logger.info(f"🗑️ Series '{watchlist_entry.show_name}' (TVDB: {watchlist_entry.tvdb_id}) no longer has PBArr tag in Sonarr, cleaning up...")

                                # Delete from mediathek_cache
                                mediathek_deleted = db.query(MediathekCache).filter(
                                    MediathekCache.tvdb_id == watchlist_entry.tvdb_id
                                ).delete()

                                # Delete from tvdb_cache
                                tvdb_deleted = db.query(TVDBCache).filter(
                                    TVDBCache.tvdb_id == watchlist_entry.tvdb_id
                                ).delete()

                                # Delete from episode_monitoring_state
                                monitoring_deleted = db.query(EpisodeMonitoringState).filter(
                                    EpisodeMonitoringState.sonarr_series_id == watchlist_entry.sonarr_series_id
                                ).delete()

                                # Delete from watch_list
                                db.delete(watchlist_entry)

                                db.commit()

                                logger.info(f"  ✅ Cleaned up series without PBArr tag '{watchlist_entry.show_name}':")
                                logger.info(f"    - {mediathek_deleted} mediathek cache entries")
                                logger.info(f"    - {tvdb_deleted} TVDB cache entries")
                                logger.info(f"    - {monitoring_deleted} monitoring state entries")
                                logger.info(f"    - 1 watchlist entry")

                                orphaned_count += 1
                            else:
                                logger.debug(f"✓ Series '{watchlist_entry.show_name}' still exists in Sonarr with PBArr tag")
                        else:
                            logger.debug(f"✓ Series '{watchlist_entry.show_name}' still exists in Sonarr")

                except Exception as e:
                    logger.error(f"Error checking series {watchlist_entry.show_name}: {e}")
                    continue

            if orphaned_count > 0:
                logger.info(f"✅ Cleaned up {orphaned_count} orphaned series")
            else:
                logger.info("No orphaned series found")

        except Exception as e:
            logger.error(f"❌ Error in orphaned series cleanup: {e}", exc_info=True)

    async def cleanup_unwatched(self):
        """Daily: Lösche Cache für nicht mehr beobachtete Shows"""
        db = SessionLocal()
        try:
            logger.info("🧹 Starting cleanup of unwatched shows...")

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
