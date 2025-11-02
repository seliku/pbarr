import httpx
import logging
from typing import Dict, Optional
from urllib.parse import urlparse
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SonarrConfig:
    """Sonarr-Konfiguration"""
    url: str
    api_key: str
    pbarr_url: str
    pbarr_docker_path: str = "/app/downloads"


class SonarrSetupWizard:
    """Wizard für automatische Sonarr-Integration"""

    def __init__(self, sonarr_url: str, api_key: str):
        self.url = sonarr_url.rstrip("/")
        self.api_key = api_key
        self.headers = {"X-Api-Key": api_key}

    async def test_connection(self) -> Dict:
        """
        Test Sonarr connection
        Returns: {"success": bool, "message": str}
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.url}/api/v3/health",
                    headers=self.headers
                )

                if resp.status_code == 401:
                    return {
                        "success": False,
                        "message": "❌ API-Key ungültig (401 Unauthorized)"
                    }
                elif resp.status_code == 404:
                    return {
                        "success": False,
                        "message": "❌ Sonarr nicht gefunden (404) - Prüfe URL und Port"
                    }
                elif resp.status_code == 200:
                    return {
                        "success": True,
                        "message": "✓ Verbindung erfolgreich"
                    }
                else:
                    return {
                        "success": False,
                        "message": f"❌ Fehler {resp.status_code}: {resp.text[:100]}"
                    }

        except httpx.TimeoutException:
            return {
                "success": False,
                "message": "❌ Timeout: Sonarr antwortet nicht - Läuft es und ist es erreichbar?"
            }
        except httpx.ConnectError:
            return {
                "success": False,
                "message": "❌ Verbindung abgelehnt - Prüfe URL, Port und Firewall"
            }
        except Exception as e:
            logger.error(f"Connection test error: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"❌ Fehler: {str(e)}"
            }

    async def create_download_client(self, pbarr_url: str, sonarr_host_download_path: str) -> Dict:
        """
        Create PBArr as Transmission download client in Sonarr

        Args:
            pbarr_url: "http://deploy:8000"
            sonarr_host_download_path: "/sonarr/downloads" (what user entered)

        Returns: {"success": bool, "message": str}
        """
        try:
            # Parse URL for host and port (Sonarr erwartet separate Felder)
            parsed = urlparse(pbarr_url)
            pbarr_host = parsed.hostname or "deploy"
            pbarr_port = parsed.port or 8000

            payload = {
                "enable": True,
                "protocol": "torrent",
                "implementation": "Transmission",
                "configContract": "TransmissionSettings",
                "name": "PBArr",
                "fields": [
                    {"name": "host", "value": pbarr_host},  # Nur Hostname!
                    {"name": "port", "value": pbarr_port},  # Port separat!
                    {"name": "username", "value": "pbarr"},
                    {"name": "password", "value": "pbarr"},
                    {
                        "name": "remotePathMappings",
                        "value": [
                            {
                                "remotePath": "/app/downloads",
                                "localPath": sonarr_host_download_path
                            }
                        ]
                    }
                ],
                "priority": 1
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.url}/api/v3/downloadclient",
                    json=payload,
                    headers=self.headers
                )

                if resp.status_code in [200, 201]:
                    logger.info("Download client created successfully")
                    return {"success": True, "message": "✓ Download-Client in Sonarr erstellt"}
                else:
                    error = resp.text
                    logger.error(f"Download client creation failed: {error}")
                    return {
                        "success": False,
                        "message": f"❌ Download-Client-Erstellung in Sonarr fehlgeschlagen: {error[:100]}"
                    }

        except Exception as e:
            logger.error(f"Create download client error: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"❌ Sonarr-Download-Client Fehler: {str(e)}"
            }

    async def create_indexer(self, pbarr_url: str, download_client_id: Optional[int] = None) -> Dict:
        """
        Create PBArr as Torznab indexer in Sonarr

        Returns: {"success": bool, "message": str}
        """
        # DEBUG: Was kommt an?
        logger.warning(f"🔴 create_indexer() RECEIVED pbarr_url: '{pbarr_url}'")

        try:
            payload = {
                "enable": False,  # Erstmal deaktivieren, damit Sonarr nicht sofort testet
                "enableRss": True,  # RSS aktivieren
                "enableAutomaticSearch": True,  # Automatische Suche einschalten
                "enableInteractiveSearch": True,  # Interaktive Suche einschalten
                "name": "PBArr",  # Name geändert von "PBArr Torznab" zu "PBArr"
                "implementation": "Torznab",
                "configContract": "TorznabSettings",
                "protocol": "torrent",
                "priority": 25,  # Hohe Priorität für PBArr-Indexer
                "fields": [
                    {"name": "baseUrl", "value": pbarr_url.rstrip('/')},
                    {"name": "apiPath", "value": "/api"},
                    {"name": "apiKey", "value": "pbarr"},
                    {"name": "categories", "value": [5000, 5020, 5030, 5040, 5045]},
                    {"name": "minimumSeeders", "value": 1},
                    {"name": "seedCriteria.seedRatio", "value": ""},
                    {"name": "seedCriteria.seedTime", "value": ""},
                    {"name": "seedCriteria.seasonPackSeedTime", "value": ""}
                ]
            }

            # Nur downloadClientId setzen, wenn verfügbar
            if download_client_id is not None:
                payload["downloadClientId"] = download_client_id

            # DEBUG: Was wird gesendet?
            logger.warning(f"🔴 Sending to Sonarr payload.fields: {payload['fields']}")
            logger.warning(f"🔴 Full baseUrl value: '{payload['fields'][0]['value']}'")

            async with httpx.AsyncClient(timeout=10.0) as client:
                logger.warning(f"🔴 Making POST to: {self.url}/api/v3/indexer")
                resp = await client.post(
                    f"{self.url}/api/v3/indexer",
                    json=payload,
                    headers=self.headers
                )

                if resp.status_code in [200, 201]:
                    logger.info("Indexer created successfully")

                    # Try to enable the indexer
                    result = resp.json()
                    indexer_id = result.get("id")
                    if indexer_id:
                        enable_result = await self._enable_indexer(indexer_id)
                        if enable_result["success"]:
                            return {"success": True, "message": "✓ Indexer in Sonarr erstellt und aktiviert"}
                        else:
                            return {"success": True, "message": "✓ Indexer in Sonarr erstellt"}
                    else:
                        return {"success": True, "message": "✓ Indexer in Sonarr erstellt"}
                else:
                    error = resp.text
                    logger.error(f"Indexer creation failed: {error}")
                    return {
                        "success": False,
                        "message": f"❌ Indexer-Erstellung in Sonarr fehlgeschlagen: {error[:100]}"
                    }

        except Exception as e:
            logger.error(f"Create indexer error: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"❌ Sonarr-Indexer-Fehler: {str(e)}"
            }

    async def setup_all(self, pbarr_url: str, sonarr_host_download_path: str) -> Dict:
        """
        Execute complete setup

        Returns:
        {
            "success": bool,
            "steps": [
                {"name": "download_client", "status": "success|error", "message": "..."},
                {"name": "indexer", "status": "success|error", "message": "..."}
            ]
        }
        """
        logger.warning(f">>> setup_all() STARTED with pbarr_url={pbarr_url}")

        results = {
            "success": False,
            "steps": []
        }

        try:
            # Download Client
            logger.warning(f">>> Calling create_download_client with: {pbarr_url}")
            dc_result = await self.create_download_client(pbarr_url, sonarr_host_download_path)
            logger.warning(f">>> create_download_client returned: {dc_result}")
            results["steps"].append({
                "name": "download_client",
                "status": "success" if dc_result["success"] else "error",
                "message": dc_result["message"]
            })

            # Get the download client ID for the indexer
            download_client_id = None
            if dc_result["success"]:
                download_client_id = await self._get_download_client_id()

            # Indexer
            logger.warning(f">>> Calling create_indexer with: {pbarr_url}")
            idx_result = await self.create_indexer(pbarr_url, download_client_id)
            logger.warning(f">>> create_indexer returned: {idx_result}")
            results["steps"].append({
                "name": "indexer",
                "status": "success" if idx_result["success"] else "error",
                "message": idx_result["message"]
            })

            # All successful?
            results["success"] = all(s["status"] == "success" for s in results["steps"])

        except Exception as e:
            logger.error(f"Setup all error: {e}", exc_info=True)
            results["steps"].append({
                "name": "setup_error",
                "status": "error",
                "message": f"❌ Setup-Fehler: {str(e)}"
            })

        return results

    async def _enable_indexer(self, indexer_id: int) -> Dict:
        """
        Enable an indexer after successful creation

        Returns: {"success": bool, "message": str}
        """
        try:
            # Erst den aktuellen Indexer holen
            async with httpx.AsyncClient(timeout=10.0) as client:
                get_resp = await client.get(
                    f"{self.url}/api/v3/indexer/{indexer_id}",
                    headers=self.headers
                )

                if get_resp.status_code != 200:
                    logger.warning(f"Could not get indexer {indexer_id} for enabling")
                    return {"success": False, "message": "Indexer konnte nicht abgerufen werden"}

                current_indexer = get_resp.json()

                # Update payload mit allen erforderlichen Feldern
                payload = current_indexer.copy()
                payload.update({
                    "enable": True,
                    "enableRss": True,
                    "enableInteractiveSearch": True
                })

                # PUT request mit vollständigem payload
                put_resp = await client.put(
                    f"{self.url}/api/v3/indexer/{indexer_id}",
                    json=payload,
                    headers=self.headers
                )

                if put_resp.status_code == 202:  # Accepted
                    logger.info(f"Indexer {indexer_id} enabled successfully")
                    return {"success": True, "message": "Indexer aktiviert"}
                else:
                    logger.warning(f"Failed to enable indexer {indexer_id}: {put_resp.text}")
                    return {"success": False, "message": "Indexer konnte nicht aktiviert werden"}

        except Exception as e:
            logger.error(f"Enable indexer error: {e}", exc_info=True)
            return {"success": False, "message": f"Aktivierungsfehler: {str(e)}"}

    async def _get_download_client_id(self) -> Optional[int]:
        """
        Get the ID of the PBArr download client

        Returns: Download client ID or None if not found
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.url}/api/v3/downloadclient",
                    headers=self.headers
                )

                if resp.status_code == 200:
                    clients = resp.json()
                    for client in clients:
                        if client.get("name") == "PBArr":
                            return client.get("id")
                    logger.warning("PBArr download client in Sonarr not found")
                    return None
                else:
                    logger.error(f"Failed to get download clients: {resp.text}")
                    return None

        except Exception as e:
            logger.error(f"Get download client ID error: {e}", exc_info=True)
            return None
