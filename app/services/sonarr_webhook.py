import asyncio
import httpx
import logging
import aiohttp
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse
from datetime import datetime

from app.models.watch_list import WatchList


logger = logging.getLogger(__name__)


class SonarrWebhookManager:
    """Manages Sonarr webhooks and API interactions"""

    def __init__(self, sonarr_url: str, api_key: str):
        self.sonarr_url = sonarr_url.rstrip('/')
        self.api_key = api_key
        self.headers = {"X-Api-Key": api_key}

        # Register Sonarr hostname as trusted (skip SOCKS5 proxy)
        from app.utils.network import register_trusted_hostname
        sonarr_hostname = urlparse(self.sonarr_url).hostname
        if sonarr_hostname:
            register_trusted_hostname(sonarr_hostname)

    async def create_webhook(self, pbarr_webhook_url: str) -> Dict:
        """
        Create PBArr webhook in Sonarr for series additions

        Args:
            pbarr_webhook_url: Full URL to PBArr webhook endpoint (e.g., "http://pbarr:8000/webhook/sonarr")

        Returns: {"success": bool, "message": str, "webhook_id": int}
        """
        try:
            # Check if webhook already exists
            existing_webhook = await self._get_existing_webhook()
            if existing_webhook:
                logger.info(f"PBArr webhook already exists with ID {existing_webhook['id']}")
                return {
                    "success": True,
                    "message": "✓ Webhook bereits in Sonarr konfiguriert",
                    "webhook_id": existing_webhook["id"]
                }

            # Parse PBArr URL for webhook URL
            parsed_pbarr = urlparse(pbarr_webhook_url)
            webhook_url = f"{parsed_pbarr.scheme}://{parsed_pbarr.netloc}/webhook/sonarr"

            payload = {
                "name": "PBArr Mediathek Webhook",
                "implementation": "Webhook",
                "configContract": "WebhookSettings",
                "enabled": True,
                "onSeriesAdd": True,
                "fields": [
                    {"name": "url", "value": webhook_url},
                    {"name": "method", "value": 1},  # POST
                    {"name": "username", "value": ""},
                    {"name": "password", "value": ""}
                ]
            }

            logger.info(f"Creating webhook with URL: {webhook_url}")

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.sonarr_url}/api/v3/notification",
                    json=payload,
                    headers=self.headers
                )

                if resp.status_code in [200, 201]:
                    result = resp.json()
                    webhook_id = result.get("id")
                    logger.info(f"Webhook created successfully with ID {webhook_id}")
                    return {
                        "success": True,
                        "message": "✓ Webhook in Sonarr erstellt",
                        "webhook_id": webhook_id
                    }
                else:
                    error = resp.text
                    logger.error(f"Webhook creation failed: {error}")
                    return {
                        "success": False,
                        "message": f"❌ Webhook-Erstellung in Sonarr fehlgeschlagen: {error[:100]}"
                    }

        except Exception as e:
            logger.error(f"Create webhook error: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"❌ Sonarr-Webhook-Fehler: {str(e)}"
            }

    async def _get_existing_webhook(self) -> Optional[Dict]:
        """
        Check if PBArr webhook already exists

        Returns: Webhook dict if found, None otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.sonarr_url}/api/v3/notification",
                    headers=self.headers
                )

                if resp.status_code == 200:
                    notifications = resp.json()
                    for notification in notifications:
                        if (notification.get("name") == "PBArr Mediathek Webhook" and
                            notification.get("implementation") == "Webhook"):
                            return notification
                    return None
                else:
                    logger.warning(f"Failed to get notifications: HTTP {resp.status_code}")
                    return None

        except Exception as e:
            logger.error(f"Get existing webhook error: {e}", exc_info=True)
            return None

    async def tag_series_in_sonarr(self, tvdb_id: str, db_session=None) -> Dict:
        """
        Tag a series in Sonarr with the PBArr tag when mediathek content is found

        Args:
            tvdb_id: TVDB ID of the series
            db_session: Optional database session (will create one if not provided)

        Returns: {"success": bool, "message": str, "tag_id": int}
        """
        db = db_session
        own_session = False

        if db is None:
            from app.database import SessionLocal
            db = SessionLocal()
            own_session = True

        try:
            # Check if series is already tagged
            watchlist_entry = db.query(WatchList).filter(WatchList.tvdb_id == tvdb_id).first()
            if not watchlist_entry:
                return {
                    "success": False,
                    "message": f"Series with TVDB ID {tvdb_id} not found in watchlist"
                }

            if watchlist_entry.tagged_in_sonarr:
                logger.debug(f"Series {tvdb_id} already tagged in Sonarr")
                return {
                    "success": True,
                    "message": "Series already tagged",
                    "tag_id": watchlist_entry.pbarr_tag_id
                }

            # Get or create PBArr tag
            tag_id = await self._get_or_create_pbarr_tag()
            if not tag_id:
                return {
                    "success": False,
                    "message": "Failed to create/get PBArr tag in Sonarr"
                }

            # Find series in Sonarr by TVDB ID
            series_data = await self._find_series_in_sonarr(tvdb_id)
            if not series_data:
                return {
                    "success": False,
                    "message": f"Series with TVDB ID {tvdb_id} not found in Sonarr"
                }

            # Add tag to series
            success = await self._add_tag_to_series(series_data["id"], tag_id)
            if not success:
                return {
                    "success": False,
                    "message": "Failed to add tag to series"
                }

            # Update watchlist entry
            watchlist_entry.tagged_in_sonarr = True
            watchlist_entry.tagged_at = datetime.utcnow()
            watchlist_entry.pbarr_tag_id = tag_id
            db.commit()

            logger.info(f"✓ Tagged series {tvdb_id} in Sonarr with PBArr tag")
            return {
                "success": True,
                "message": "Series tagged successfully",
                "tag_id": tag_id
            }

        except Exception as e:
            logger.error(f"Tag series error for TVDB {tvdb_id}: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Tagging failed: {str(e)}"
            }
        finally:
            if own_session and db:
                db.close()

    async def _get_or_create_pbarr_tag(self) -> Optional[int]:
        """
        Get existing PBArr tag or create a new one

        Returns: Tag ID or None if failed
        """
        try:
            # First check if PBArr tag already exists
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.sonarr_url}/api/v3/tag",
                    headers=self.headers
                )

                if resp.status_code == 200:
                    tags = resp.json()
                    for tag in tags:
                        if tag.get("label", "").lower() == "pbarr":
                            logger.debug(f"Found existing PBArr tag with ID {tag['id']}")
                            return tag["id"]

            # Tag doesn't exist, try to create it
            async with httpx.AsyncClient(timeout=10.0) as client:
                payload = {"label": "PBArr"}
                resp = await client.post(
                    f"{self.sonarr_url}/api/v3/tag",
                    json=payload,
                    headers=self.headers
                )

                if resp.status_code in [200, 201]:
                    result = resp.json()
                    tag_id = result.get("id")
                    logger.info(f"Created new PBArr tag with ID {tag_id}")
                    return tag_id
                elif resp.status_code == 409 or "UNIQUE constraint failed" in resp.text:
                    # Tag was created by another process, try to find it again
                    logger.warning("PBArr tag creation failed due to constraint, checking again...")
                    await asyncio.sleep(0.5)  # Brief pause before retry
                    async with httpx.AsyncClient(timeout=10.0) as retry_client:
                        retry_resp = await retry_client.get(
                            f"{self.sonarr_url}/api/v3/tag",
                            headers=self.headers
                        )
                        if retry_resp.status_code == 200:
                            retry_tags = retry_resp.json()
                            for tag in retry_tags:
                                if tag.get("label", "").lower() == "pbarr":
                                    logger.info(f"Found PBArr tag after retry with ID {tag['id']}")
                                    return tag["id"]
                            # If still not found, log all tags for debugging
                            logger.warning(f"PBArr tag not found. Available tags: {[t.get('label') for t in retry_tags]}")
                        else:
                            logger.error(f"Failed to get tags on retry: HTTP {retry_resp.status_code}")
                    logger.error("Could not find PBArr tag after constraint error")
                    return None
                else:
                    logger.error(f"Failed to create PBArr tag: HTTP {resp.status_code} - {resp.text}")
                    return None

        except Exception as e:
            logger.error(f"Get/create PBArr tag error: {e}", exc_info=True)
            return None

    async def _find_series_in_sonarr(self, tvdb_id: str) -> Optional[Dict]:
        """
        Find series in Sonarr by TVDB ID

        Returns: Series data dict or None if not found
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.sonarr_url}/api/v3/series",
                    headers=self.headers
                )

                if resp.status_code == 200:
                    series_list = resp.json()
                    for series in series_list:
                        if str(series.get("tvdbId", "")) == tvdb_id:
                            return series
                    return None
                else:
                    logger.error(f"Failed to fetch series from Sonarr: {resp.text}")
                    return None

        except Exception as e:
            logger.error(f"Find series error: {e}", exc_info=True)
            return None

    async def _add_tag_to_series(self, series_id: int, tag_id: int) -> bool:
        """
        Add tag to a series in Sonarr

        Args:
            series_id: Sonarr series ID
            tag_id: Tag ID to add

        Returns: True if successful
        """
        try:
            # First get current series data
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.sonarr_url}/api/v3/series/{series_id}",
                    headers=self.headers
                )

                if resp.status_code != 200:
                    logger.error(f"Failed to get series {series_id}: {resp.text}")
                    return False

                series_data = resp.json()
                current_tags = series_data.get("tags", [])

                # Add tag if not already present
                if tag_id not in current_tags:
                    current_tags.append(tag_id)

                    # Update series with new tags
                    update_payload = series_data.copy()
                    update_payload["tags"] = current_tags

                    resp = await client.put(
                        f"{self.sonarr_url}/api/v3/series/{series_id}",
                        json=update_payload,
                        headers=self.headers
                    )

                    if resp.status_code == 202:  # Accepted
                        logger.debug(f"Added tag {tag_id} to series {series_id}")
                        return True
                    else:
                        logger.error(f"Failed to update series tags: {resp.text}")
                        return False
                else:
                    logger.debug(f"Series {series_id} already has tag {tag_id}")
                    return True

        except Exception as e:
            logger.error(f"Add tag to series error: {e}", exc_info=True)
            return False

    async def get_monitored_episodes_without_files(self, sonarr_series_id: int) -> List[Dict]:
        """
        Get all monitored episodes from Sonarr that don't have files yet (hasFile=False)

        Args:
            sonarr_series_id: Sonarr series ID

        Returns:
            List of episode dicts with seasonNumber, episodeNumber, etc.
            Only episodes where monitored=True AND hasFile=False
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.sonarr_url}/api/v3/episode?seriesId={sonarr_series_id}",
                    headers=self.headers
                )

                if resp.status_code == 200:
                    episodes = resp.json()
                    # Filter: monitored=True AND hasFile=False (Sonarr is MISSING these files)
                    monitored_missing = [
                        ep for ep in episodes
                        if ep.get("monitored") and not ep.get("hasFile", False)  # Default to False if hasFile not present
                    ]
                    logger.debug(f"Found {len(monitored_missing)} monitored episodes without files for series {sonarr_series_id}")
                    return monitored_missing
                else:
                    logger.error(f"Failed to get episodes for series {sonarr_series_id}: {resp.text}")
                    return []

        except Exception as e:
            logger.error(f"Get monitored episodes error for series {sonarr_series_id}: {e}", exc_info=True)
            return []

    async def get_all_monitored_episodes(self, sonarr_series_id: int) -> List[Dict]:
        """
        Get all monitored episodes from Sonarr (regardless of hasFile status)

        Args:
            sonarr_series_id: Sonarr series ID

        Returns:
            List of episode dicts with seasonNumber, episodeNumber, etc.
            Only episodes where monitored=True
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.sonarr_url}/api/v3/episode?seriesId={sonarr_series_id}",
                    headers=self.headers
                )

                if resp.status_code == 200:
                    episodes = resp.json()
                    # Filter: only monitored=True
                    monitored_episodes = [
                        ep for ep in episodes
                        if ep.get("monitored")
                    ]
                    logger.debug(f"Found {len(monitored_episodes)} monitored episodes for series {sonarr_series_id}")
                    return monitored_episodes
                else:
                    logger.error(f"Failed to get episodes for series {sonarr_series_id}: {resp.text}")
                    return []

        except Exception as e:
            logger.error(f"Get monitored episodes error for series {sonarr_series_id}: {e}", exc_info=True)
            return []

    async def test_webhook_connection(self, pbarr_webhook_url: str) -> Dict:
        """
        Test webhook connection by sending a test payload

        Returns: {"success": bool, "message": str}
        """
        try:
            # Parse PBArr URL for webhook URL
            parsed_pbarr = urlparse(pbarr_webhook_url)
            webhook_url = f"{parsed_pbarr.scheme}://{parsed_pbarr.netloc}/webhook/sonarr"

            test_payload = {
                "eventType": "Test",
                "series": {
                    "id": 999,
                    "title": "Test Series",
                    "tvdbId": 12345
                }
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    webhook_url,
                    json=test_payload,
                    headers={"Content-Type": "application/json"}
                )

                if resp.status_code == 200:
                    return {
                        "success": True,
                        "message": "✓ Webhook-Verbindung erfolgreich getestet"
                    }
                else:
                    return {
                        "success": False,
                        "message": f"❌ Webhook-Test fehlgeschlagen: HTTP {resp.status_code}"
                    }

        except httpx.ConnectError:
            return {
                "success": False,
                "message": "❌ Webhook-URL nicht erreichbar - Prüfe PBArr-URL"
            }
        except Exception as e:
            logger.error(f"Test webhook connection error: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"❌ Webhook-Test-Fehler: {str(e)}"
            }

    async def trigger_import_scan(self, path: str = "/downloads") -> Dict:
        """
        Trigger Sonarr to scan the download folder and import files

        Args:
            path: Path to scan (from Sonarr's perspective, default: "/downloads")

        Returns: {"success": bool, "message": str, "command_id": int}
        """
        try:
            command_payload = {
                "name": "DownloadedEpisodesScan",
                "path": path
            }

            logger.info(f"Triggering Sonarr import scan for path: {path}")

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.sonarr_url}/api/v3/command",
                    json=command_payload,
                    headers=self.headers
                )

                if resp.status_code in [200, 201]:
                    result = resp.json()
                    command_id = result.get("id")
                    logger.info(f"✅ Import scan triggered successfully: command ID {command_id}")
                    return {
                        "success": True,
                        "message": f"✓ Import-Scan für {path} gestartet",
                        "command_id": command_id
                    }
                else:
                    error = resp.text
                    logger.error(f"Failed to trigger import scan: {error}")
                    return {
                        "success": False,
                        "message": f"❌ Import-Scan fehlgeschlagen: {error[:100]}"
                    }

        except Exception as e:
            logger.error(f"Trigger import scan error: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"❌ Import-Scan-Fehler: {str(e)}"
            }

    async def rescan_series(self, sonarr_series_id: int) -> Dict:
        """
        Trigger Sonarr to rescan a specific series for new episodes

        Args:
            sonarr_series_id: Sonarr series ID to rescan

        Returns: {"success": bool, "message": str, "command_id": int}
        """
        try:
            command_payload = {
                "name": "RescanSeries",
                "seriesId": sonarr_series_id
            }

            logger.info(f"Triggering Sonarr rescan for series ID: {sonarr_series_id}")

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.sonarr_url}/api/v3/command",
                    json=command_payload,
                    headers=self.headers
                )

                if resp.status_code in [200, 201]:
                    result = resp.json()
                    command_id = result.get("id")
                    logger.info(f"✅ Series rescan triggered successfully: command ID {command_id}")
                    return {
                        "success": True,
                        "message": f"✓ Rescan für Serie {sonarr_series_id} gestartet",
                        "command_id": command_id
                    }
                else:
                    error = resp.text
                    logger.error(f"Failed to trigger series rescan: {error}")
                    return {
                        "success": False,
                        "message": f"❌ Series-Rescan fehlgeschlagen: {error[:100]}"
                    }

        except Exception as e:
            logger.error(f"Series rescan error for ID {sonarr_series_id}: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"❌ Series-Rescan-Fehler: {str(e)}"
            }

    async def get_series_info(self, sonarr_series_id: int) -> Optional[Dict]:
        """
        Get series information from Sonarr by ID

        Args:
            sonarr_series_id: Sonarr series ID

        Returns: Series dict with title, path, seasonFolder, etc. or None if not found
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.sonarr_url}/api/v3/series/{sonarr_series_id}",
                    headers=self.headers
                )

                if resp.status_code == 200:
                    series_data = resp.json()
                    logger.debug(f"Got series info for ID {sonarr_series_id}: {series_data.get('title')}")
                    return series_data
                else:
                    logger.error(f"Failed to get series {sonarr_series_id}: HTTP {resp.status_code}")
                    return None

        except Exception as e:
            logger.error(f"Error getting series info for ID {sonarr_series_id}: {e}", exc_info=True)
            return None

    async def get_series_season_folder_setting(self, sonarr_series_id: int) -> Optional[bool]:
        """
        Get the seasonFolder setting for a series from Sonarr

        Args:
            sonarr_series_id: Sonarr series ID

        Returns: True if series uses season folders, False if flat structure, None if error
        """
        try:
            series_info = await self.get_series_info(sonarr_series_id)
            if series_info and "seasonFolder" in series_info:
                season_folder = series_info["seasonFolder"]
                logger.debug(f"Series {sonarr_series_id} seasonFolder setting: {season_folder}")
                return season_folder
            else:
                logger.warning(f"seasonFolder setting not found in series info for ID {sonarr_series_id}")
                return None

        except Exception as e:
            logger.error(f"Error getting season folder setting for series {sonarr_series_id}: {e}", exc_info=True)
            return None

    async def get_episode(self, series_id: int, season: int, episode: int) -> Dict:
        """
        Get episode details from Sonarr API

        Args:
            series_id: Sonarr series ID
            season: Season number
            episode: Episode number

        Returns: Episode dict or empty dict if not found
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.sonarr_url}/api/v3/episode?seriesId={series_id}",
                    headers=self.headers
                )

                if resp.status_code == 200:
                    episodes = resp.json()
                    for ep in episodes:
                        if (ep.get("seasonNumber") == season and
                            ep.get("episodeNumber") == episode):
                            logger.debug(f"Got episode info for S{season:02d}E{episode:02d}: {ep.get('title')}")
                            return ep
                    logger.warning(f"Episode S{season:02d}E{episode:02d} not found in series {series_id}")
                    return {"title": ""}
                else:
                    logger.error(f"Failed to get episodes for series {series_id}: HTTP {resp.status_code}")
                    return {"title": ""}

        except Exception as e:
            logger.error(f"Error getting episode info for series {series_id} S{season}E{episode}: {e}", exc_info=True)
            return {"title": ""}

    async def trigger_disk_scan(self, series_id: int) -> Dict:
        """
        Trigger Sonarr to rescan a series for new files

        Args:
            series_id: Sonarr series ID to rescan

        Returns: {"success": bool, "message": str}
        """
        try:
            command = {
                "name": "RescanSeries",
                "seriesId": series_id
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.sonarr_url}/api/v3/command",
                    json=command,
                    headers=self.headers
                )

                if resp.status_code in [200, 201]:
                    result = resp.json()
                    command_id = result.get("id")
                    logger.info(f"✅ Triggered RescanSeries for series {series_id}: command ID {command_id}")
                    return {
                        "success": True,
                        "message": f"✓ Rescan für Serie {series_id} gestartet",
                        "command_id": command_id
                    }
                else:
                    error = resp.text
                    logger.error(f"Failed to trigger series rescan: {error}")
                    return {
                        "success": False,
                        "message": f"❌ Series-Rescan fehlgeschlagen: {error[:100]}"
                    }

        except Exception as e:
            logger.error(f"Error triggering disk scan for series {series_id}: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"❌ Series-Rescan-Fehler: {str(e)}"
            }



    async def send_command(self, command_name: str, path: str = None) -> Dict:
        """
        Send command to Sonarr

        Args:
            command_name: Name of the command (e.g., "DownloadedEpisodesScan")
            path: Optional path parameter

        Returns: {"success": bool, "message": str}
        """
        try:
            payload = {"name": command_name}
            if path:
                payload["path"] = path

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.sonarr_url}/api/v3/command",
                    json=payload,
                    headers=self.headers
                )

                if resp.status_code in [200, 201]:
                    result = resp.json()
                    command_id = result.get("id")
                    logger.info(f"✅ Sent {command_name} command successfully: ID {command_id}")
                    return {
                        "success": True,
                        "message": f"✓ {command_name} command sent",
                        "command_id": command_id
                    }
                else:
                    error = resp.text
                    logger.error(f"Failed to send {command_name} command: {error}")
                    return {
                        "success": False,
                        "message": f"❌ {command_name} command failed: {error[:100]}"
                    }

        except Exception as e:
            logger.error(f"Error sending {command_name} command: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"❌ {command_name} command error: {str(e)}"
            }
