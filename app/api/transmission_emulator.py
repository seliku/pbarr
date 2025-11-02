from fastapi import APIRouter, Request, Response, Depends
from sqlalchemy.orm import Session
from datetime import datetime
import logging
import json
from typing import Dict, List, Any, Optional

from app.database import get_db
from app.models.download import Download
from app.models.config import Config
from app.services.download_manager import DownloadManager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["transmission"])

# Transmission Status-Mapping
TRANSMISSION_STATUS_MAP = {
    "queued": 0,       # Paused
    "downloading": 4,  # Downloading
    "completed": 6,    # Seeding
    "failed": 0,       # Stopped
    "cancelled": 0     # Stopped
}


def get_download_path(db: Session) -> str:
    """Lese Sonarr Download-Pfad aus Config-Tabelle"""
    try:
        config = db.query(Config).filter_by(key="sonarr_download_path_host").first()
        if config and config.value:
            logger.info(f"Using download path from config: {config.value}")
            return config.value
        else:
            logger.warning("sonarr_download_path_host config not found or empty")
    except Exception as e:
        logger.warning(f"Could not read sonarr_download_path_host from config: {e}")

    return "/downloads"  # Fallback

def format_torrent(download: Download, download_path: str) -> Dict[str, Any]:
    """Wandelt einen Download in ein Transmission-Torrent-Objekt um"""

    status = TRANSMISSION_STATUS_MAP.get(download.status, 0)

    # Berechnung des Fortschritts (0-100%)
    percent_done = download.progress / 100 if download.progress is not None else 0

    return {
        "id": download.id,
        "name": download.filename,
        "hashString": f"pbarr-{download.id}",  # Fake Hash
        "status": status,
        "downloadDir": download_path,  # Verwende Config-Pfad direkt
        "percentDone": percent_done,
        "totalSize": 100000000,  # Dummy-Wert: 100MB
        "leftUntilDone": 100000000 * (1 - percent_done),
        "rateDownload": 1000000 if status == 4 else 0,  # 1MB/s beim Downloaden
        "rateUpload": 0,
        "uploadRatio": 0,
        "uploadedEver": 0,
        "downloadedEver": 100000000 * percent_done,
        "addedDate": int(download.created_at.timestamp()) if download.created_at else 0,
        "doneDate": int(download.completed_at.timestamp()) if download.completed_at else 0,
        "queuePosition": 0,
        "trackers": [
            {"announce": "http://example.com/announce", "id": 1, "scrape": "http://example.com/scrape"}
        ],
        "peersConnected": 5 if status == 4 else 0,
        "startDate": int(download.started_at.timestamp()) if download.started_at else 0,
        "isFinished": status == 6,
        "eta": 3600 if status == 4 else -1,  # 1 Stunde ETA oder -1 wenn nicht aktiv
        "error": 0,
        "errorString": "",
        "downloadLimit": -1,
        "downloadLimited": False,
        "uploadLimit": -1,
        "uploadLimited": False,
        "seedRatioLimit": 1,
        "seedRatioMode": 1
    }


# GET-Route für den initialen Verbindungstest
@router.get("/pbarr/rpc")
@router.get("/transmission/rpc")
async def transmission_rpc_get(request: Request):
    """
    GET-Route für den initialen Verbindungstest von Sonarr
    Sendet 409 Conflict mit der Session-ID zurück
    """
    logger.info("GET /transmission/rpc - Initialer Verbindungstest von Sonarr")
    
    # Immer mit 409 und Session-ID antworten
    headers = {
        "X-Transmission-Session-Id": "pbarr-transmission-session",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type, X-Transmission-Session-Id",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS"
    }
    
    return Response(
        status_code=409,
        content=json.dumps({"result": "error", "message": "Bitte POST mit Session-ID verwenden"}),
        headers=headers,
        media_type="application/json"
    )


# POST-Route für die eigentlichen RPC-Aufrufe
@router.post("/pbarr/rpc")
@router.post("/transmission/rpc")  # Standardpfad hinzufügen für bessere Kompatibilität
async def transmission_rpc(request: Request, db: Session = Depends(get_db)):
    """
    Emuliert die Transmission RPC API für die Sonarr-Integration
    """
    try:
        # Debug-Ausgabe aller Header und der URL
        logger.info(f"Request URL: {request.url}")
        for header_name, header_value in request.headers.items():
            logger.info(f"Header {header_name}: {header_value}")
        
        # Transmission-Authentifizierungsflow:
        # 1. ERST Session-ID prüfen
        session_id = request.headers.get("X-Transmission-Session-Id")
        if not session_id:
            # Wenn keine Session-ID vorhanden ist, sende eine mit 409 Conflict zurück
            # Der Client sollte die Anfrage mit dieser Session-ID wiederholen
            logger.info("Keine Session-ID gefunden, sende 409 mit Session-ID")
            headers = {
                "X-Transmission-Session-Id": "pbarr-transmission-session",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type, X-Transmission-Session-Id",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS"
            }
            return Response(
                status_code=409,
                content=json.dumps({"result": "error", "message": "Session-ID fehlt"}),
                headers=headers,
                media_type="application/json"
            )
        
        # 2. Session-ID ist OK - Request-Body parsen
        logger.info(f"Session-ID OK: {session_id}")
        
        # Lese den Request-Body
        body = await request.json()
        method = body.get("method")
        arguments = body.get("arguments", {})
        tag = body.get("tag", 0)
        
        # 3. Credentials (falls vorhanden) - aber wir ignorieren sie
        # Sonarr sendet Anmeldeinformationen im Request-Body, nicht als Authorization-Header!
        rpc_username = body.get("rpc-username")
        rpc_password = body.get("rpc-password")
        if rpc_username or rpc_password:
            logger.info(f"Auth-Credentials im Request-Body empfangen (ignoriert): {rpc_username}")
        
        logger.info(f"Transmission RPC Aufruf: Methode={method}, Argumente={arguments}")

        # Standard-Erfolgsantwort
        response = {
            "result": "success",
            "arguments": {},
            "tag": tag
        }
        
        if method == "session-get":
            # Lese Download-Pfad aus Config
            download_path = get_download_path(db)

            # Sitzungsinformationen zurückgeben (Sonarr prüft dies beim Test der Verbindung)
            response["arguments"] = {
                "alt-speed-down": 0,
                "alt-speed-enabled": False,
                "alt-speed-time-begin": 0,
                "alt-speed-time-day": 0,
                "alt-speed-time-enabled": False,
                "alt-speed-time-end": 0,
                "alt-speed-up": 0,
                "blocklist-enabled": False,
                "blocklist-size": 0,
                "blocklist-url": "",
                "cache-size-mb": 4,
                "config-dir": "/config",
                "download-dir": download_path,  # Verwende Config-Pfad
                "download-dir-free-space": 100000000000,  # 100 GB frei
                "download-queue-enabled": True,
                "download-queue-size": 5,
                "encryption": "preferred",
                "idle-seeding-limit": 30,
                "idle-seeding-limit-enabled": False,
                "incomplete-dir": "/downloads/incomplete",
                "incomplete-dir-enabled": True,
                "peer-limit-global": 200,
                "peer-limit-per-torrent": 50,
                "peer-port": 51413,
                "peer-port-random-on-start": False,
                "pex-enabled": True,
                "port-forwarding-enabled": False,
                "queue-stalled-enabled": True,
                "queue-stalled-minutes": 30,
                "rename-partial-files": True,
                "rpc-version": 16,  # Aktuelle RPC-Version von Transmission
                "rpc-version-minimum": 14,
                "script-torrent-done-enabled": False,
                "script-torrent-done-filename": "",
                "seed-queue-enabled": False,
                "seed-queue-size": 10,
                "seedRatioLimit": 2,
                "seedRatioLimited": False,
                "speed-limit-down": 100,
                "speed-limit-down-enabled": False,
                "speed-limit-up": 100,
                "speed-limit-up-enabled": False,
                "start-added-torrents": True,
                "trash-original-torrent-files": False,
                "units": {
                    "memory-bytes": 1024,
                    "memory-units": ["KiB", "MiB", "GiB", "TiB"],
                    "size-bytes": 1000,
                    "size-units": ["kB", "MB", "GB", "TB"],
                    "speed-bytes": 1000,
                    "speed-units": ["kB/s", "MB/s", "GB/s", "TB/s"]
                },
                "utp-enabled": True,
                "version": "3.00 (pbarr emulation)"
            }
        
        elif method == "torrent-get":
            # Lese Download-Pfad aus Config
            download_path = get_download_path(db)

            # Torrent-Informationen abrufen
            fields = arguments.get("fields", [])
            torrent_ids = arguments.get("ids", [])

            # Alle Downloads aus der Datenbank abrufen
            if torrent_ids and torrent_ids != "recently-active":
                downloads = db.query(Download).filter(Download.id.in_(torrent_ids)).all()
            else:
                downloads = db.query(Download).all()

            # Übergebe download_path an format_torrent
            torrents = [format_torrent(download, download_path) for download in downloads]

            response["arguments"] = {
                "torrents": torrents,
                "removed": []  # Keine entfernten Torrents für diesen Aufruf
            }
        
        elif method == "torrent-add":
            # Neuen Torrent hinzufügen
            url = arguments.get("filename") or arguments.get("metainfo")
            download_dir = arguments.get("download-dir", "/downloads/complete")
            paused = arguments.get("paused", False)
            
            if not url:
                response["result"] = "error"
                response["arguments"] = {"errorString": "URL oder Metainfo erforderlich"}
            else:
                # Fiktiver URL für Sonarr, wird später durch den wirklichen Link in PBArr ersetzt
                file_name = url.split("/")[-1] if "/" in url else url
                
                download = Download(
                    filename=file_name,
                    status="queued" if paused else "downloading",
                    created_at=datetime.utcnow(),
                    source_url=url,
                    episode_id="unknown"  # Hier muss später die korrekte Episode-ID eingetragen werden
                )
                
                db.add(download)
                db.commit()
                db.refresh(download)
                
                torrent_added = {
                    "id": download.id,
                    "name": download.filename,
                    "hashString": f"pbarr-{download.id}"
                }
                
                response["arguments"] = {"torrent-added": torrent_added}
                logger.info(f"Neuer Download hinzugefügt: {file_name} (ID: {download.id})")
        
        elif method == "torrent-remove":
            # Torrent entfernen
            ids = arguments.get("ids", [])
            delete_local_data = arguments.get("delete-local-data", False)
            
            for torrent_id in ids:
                download = db.query(Download).filter_by(id=int(torrent_id)).first()
                if download:
                    download.status = "cancelled"
                    db.commit()
                    logger.info(f"Download {torrent_id} wurde als gelöscht markiert")
        
        elif method == "torrent-start" or method == "torrent-start-now":
            # Torrent starten
            ids = arguments.get("ids", [])
            
            for torrent_id in ids:
                download = db.query(Download).filter_by(id=int(torrent_id)).first()
                if download and download.status == "queued":
                    download.status = "downloading"
                    download.started_at = datetime.utcnow()
                    db.commit()
                    logger.info(f"Download {torrent_id} wurde gestartet")
        
        elif method == "torrent-stop":
            # Torrent stoppen
            ids = arguments.get("ids", [])
            
            for torrent_id in ids:
                download = db.query(Download).filter_by(id=int(torrent_id)).first()
                if download and download.status == "downloading":
                    download.status = "queued"
                    db.commit()
                    logger.info(f"Download {torrent_id} wurde angehalten")
        
        elif method == "torrent-set":
            # Torrent-Eigenschaften setzen (z.B. Labels)
            ids = arguments.get("ids", [])
            labels = arguments.get("labels", [])
            
            if labels and ids:
                logger.info(f"Setze Labels {labels} für Torrents {ids}")
                # In PBArr werden Labels derzeit nicht gespeichert, aber wir protokollieren
                # die Anfrage für zukünftige Implementierungen
        
        elif method == "free-space":
            # Verfügbaren Speicherplatz abfragen
            path = arguments.get("path", "/downloads/complete")
            response["arguments"] = {
                "path": path,
                "size-bytes": 500000000000  # 500 GB frei (fiktiver Wert)
            }
        
        elif method == "port-test":
            # Test, ob der Peer-Port erreichbar ist
            response["arguments"] = {
                "port-is-open": True
            }
            
        else:
            logger.warning(f"Nicht implementierte Transmission-Methode: {method}")
        
        # CORS-Header für die Antwort hinzufügen
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type, X-Transmission-Session-Id",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "X-Transmission-Session-Id": session_id or "pbarr-transmission-session"
        }
        return Response(
            content=json.dumps(response),
            headers=headers,
            media_type="application/json"
        )
            
    except Exception as e:
        logger.error(f"Transmission RPC Error: {str(e)}", exc_info=True)
        error_response = {
            "result": "error",
            "arguments": {"errorString": str(e)},
            "tag": body.get("tag", 0) if 'body' in locals() else 0
        }
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type, X-Transmission-Session-Id",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "X-Transmission-Session-Id": "pbarr-transmission-session"
        }
        return Response(
            content=json.dumps(error_response),
            headers=headers,
            media_type="application/json"
        )


# OPTIONS-Endpunkt für CORS preflight requests
@router.options("/pbarr/rpc")
@router.options("/transmission/rpc")
async def transmission_options(request: Request):
    """
    Behandelt OPTIONS-Anfragen für CORS
    """
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type, X-Transmission-Session-Id",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "X-Transmission-Session-Id": "pbarr-transmission-session"
    }
    return Response(status_code=200, headers=headers)
