import logging
import aiohttp
from xml.etree import ElementTree as ET
from datetime import datetime
from typing import Dict, List, Optional
from sqlalchemy.orm import Session

from app.models.watch_list import WatchList
from app.database import SessionLocal
from app.utils.network import create_aiohttp_session, get_proxy_for_url

logger = logging.getLogger(__name__)


class MediathekImporter:
    """Importiert bestehende Serien aus Sonarr und prüft Mediathek-Verfügbarkeit"""

    async def search_mediathek_for_series(self, show_name: str) -> bool:
        """
        Search MediathekViewWeb for a series and return if any results found

        Args:
            show_name: Name of the series to search for

        Returns:
            True if series has episodes available in mediathek, False otherwise
        """
        try:
            logger.debug(f"Searching MediathekViewWeb for: {show_name}")

            # Build search query like the cacher does
            query_name = show_name.replace(' ', '%2C')
            feed_url = f"https://mediathekviewweb.de/feed?query=!ard%20%23{query_name}%20%3E20"

            proxy_url = get_proxy_for_url(feed_url)
            async with create_aiohttp_session(proxy_url=proxy_url) as session:
                async with session.get(feed_url, timeout=10) as resp:
                    if resp.status != 200:
                        logger.warning(f"Mediathek search failed for {show_name}: HTTP {resp.status}")
                        return False

                    content = await resp.text()
                    root = ET.fromstring(content)

                    # Count items in feed
                    items = root.findall('.//item')
                    item_count = len(items)

                    logger.debug(f"Found {item_count} results for {show_name}")

                    return item_count > 0

        except Exception as e:
            logger.error(f"Mediathek search error for {show_name}: {e}")
            return False

    async def import_existing_series_from_sonarr(
        self,
        sonarr_url: str,
        api_key: str,
        db: Session
    ) -> Dict:
        """
        Import existing series from Sonarr and add available ones to watchlist

        Args:
            sonarr_url: Sonarr base URL
            api_key: Sonarr API key
            db: Database session

        Returns:
            {"imported": int, "skipped": int, "total": int, "errors": List[str]}
        """
        import httpx
        from urllib.parse import urljoin

        result = {
            "imported": 0,
            "skipped": 0,
            "total": 0,
            "errors": []
        }

        try:
            logger.info("Starting import of existing series from Sonarr")

            # Fetch all series from Sonarr
            series_url = urljoin(sonarr_url, "/api/v3/series")
            headers = {"X-Api-Key": api_key}

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(series_url, headers=headers)

                if resp.status_code != 200:
                    error_msg = f"Failed to fetch series from Sonarr: HTTP {resp.status_code}"
                    logger.error(error_msg)
                    result["errors"].append(error_msg)
                    return result

                sonarr_series = resp.json()
                result["total"] = len(sonarr_series)

                logger.info(f"Found {len(sonarr_series)} series in Sonarr")

                for series in sonarr_series:
                    try:
                        tvdb_id = str(series.get("tvdbId", ""))
                        title = series.get("title", "")
                        sonarr_series_id = series.get("id")

                        if not tvdb_id or not title:
                            logger.warning(f"Skipping series without tvdbId or title: {series}")
                            result["skipped"] += 1
                            continue

                        # Check if already in watchlist
                        existing = db.query(WatchList).filter(WatchList.tvdb_id == tvdb_id).first()
                        if existing:
                            logger.debug(f"Series {title} already in watchlist")
                            result["skipped"] += 1
                            continue

                        # Search MediathekViewWeb for this series
                        has_mediathek_content = await self.search_mediathek_for_series(title)

                        if has_mediathek_content:
                            # Add to watchlist
                            watchlist_entry = WatchList(
                                tvdb_id=tvdb_id,
                                show_name=title,
                                sonarr_series_id=sonarr_series_id,
                                import_source="sonarr_import"
                            )
                            db.add(watchlist_entry)
                            db.commit()

                            result["imported"] += 1
                            logger.info(f"✓ Imported {title} (TVDB: {tvdb_id})")
                        else:
                            logger.debug(f"No mediathek content found for {title}")
                            result["skipped"] += 1

                    except Exception as e:
                        error_msg = f"Error processing series {series.get('title', 'Unknown')}: {str(e)}"
                        logger.error(error_msg)
                        result["errors"].append(error_msg)
                        result["skipped"] += 1
                        continue

            logger.info(f"Import complete: {result['imported']} imported, {result['skipped']} skipped")

        except Exception as e:
            error_msg = f"Import failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            result["errors"].append(error_msg)

        return result


# Global instance
importer = MediathekImporter()
