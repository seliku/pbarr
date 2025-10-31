"""
NZBGet API Emulator für PBArr

Emuliert die NZBGet JSON-RPC API für Sonarr-Integration:
- /jsonrpc Endpunkt (wichtig!)
- Mapping von NZBGet-Befehlen auf PBArr-Funktionen
"""
import logging
import json
from fastapi import APIRouter, Request, Depends, Response
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Dict, List, Any, Optional

from app.database import get_db
from app.models.download import Download
from app.services.download_manager import DownloadManager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["nzbget"])

# Konstanten für die Status-Übersetzung
NZBGET_STATUS_MAP = {
    "queued": "QUEUED",
    "downloading": "DOWNLOADING",
    "completed": "SUCCESS", 
    "failed": "FAILURE",
    "cancelled": "DELETED",
}

# Format für die Geschichte und Queue
def format_history_item(download: Download) -> Dict[str, Any]:
    return {
        "NZBID": download.id,
        "NZBName": download.filename,
        "Status": NZBGET_STATUS_MAP.get(download.status, "UNKNOWN"),
        "FileSizeMB": 0,  # Nicht verfügbar vor dem Download
        "DownloadTimeSec": (
            int((download.completed_at - download.started_at).total_seconds())
            if download.completed_at and download.started_at 
            else 0
        ),
        "ParStatus": "SUCCESS",
        "UnpackStatus": "NONE",
        "MoveStatus": "SUCCESS" if download.status == "completed" else "NONE",
        "MessageCount": 0,
        "Category": "sonarr",
        "DestDir": "/app/downloads/completed",
        "FinalDir": "/app/downloads/completed",
        "DownloadedSizeMB": 0,  # Nicht verfügbar vor dem Download
        "DownloadTime": download.completed_at.strftime("%Y-%m-%d %H:%M:%S") if download.completed_at else "",
        "Parameters": [
            {"Name": "episodeId", "Value": download.episode_id or ""},
        ]
    }

def format_queue_item(download: Download) -> Dict[str, Any]:
    return {
        "NZBID": download.id,
        "NZBName": download.filename,
        "NZBPriority": 0,
        "NZBCategory": "sonarr",
        "ActiveDownloads": 1 if download.status == "downloading" else 0,
        "FileSizeMB": 0,  # Nicht verfügbar vor dem Download
        "SizeLo": 0,
        "SizeHi": 0,
        "RemainingSizeLo": 0,
        "RemainingSizeHi": 0,
        "DownloadedSizeLo": 0,
        "DownloadedSizeHi": 0,
        "DownloadTimeSec": int((datetime.utcnow() - download.started_at).total_seconds()) if download.started_at else 0,
        "PausedSizeLo": 0,
        "PausedSizeHi": 0,
        "Progress": download.progress or 0,  # Wir haben das direkt
        "Status": NZBGET_STATUS_MAP.get(download.status, "UNKNOWN"),
        "Parameters": [
            {"Name": "episodeId", "Value": download.episode_id or ""},
        ],
        "ServerStats": [],
        "MinPriority": 0,
        "MaxPriority": 0,
        "NZBIndex": 0,
    }

def format_version() -> Dict[str, str]:
    return {
        "result": {
            "version": "21.1",  # Eine neuere NZBGet-Version (Kompatibilität)
            "AppVersion": "PBArr-NZBGet-Emulator/1.0",
            "ServerTime": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        }
    }

@router.post("/jsonrpc")
async def jsonrpc_handler(request: Request, db: Session = Depends(get_db)):
    """
    Emuliert den NZBGet JSON-RPC-Endpunkt für Sonarr
    """
    try:
        # Request Body auslesen
        data = await request.json()
        
        # Methode und Parameter extrahieren
        method = data.get("method", "")
        params = data.get("params", [])
        
        logger.info(f"NZBGet RPC Call: {method} {params}")
        
        # Die häufigsten RPC-Methoden emulieren
        if method == "version":
            return format_version()
            
        elif method == "listgroups":
            # Aktive Downloads (Queue) zurückgeben
            queue = db.query(Download).filter(
                Download.status.in_(["queued", "downloading"])
            ).order_by(Download.created_at.desc()).all()
            
            return {
                "result": [format_queue_item(item) for item in queue]
            }
            
        elif method == "history":
            # Abgeschlossene Downloads
            history = db.query(Download).filter(
                Download.status.in_(["completed", "failed", "cancelled"])
            ).order_by(Download.created_at.desc()).all()
            
            return {
                "result": [format_history_item(item) for item in history]
            }
            
        elif method == "append":
            # Neuen Download hinzufügen
            # Parameter: nzbname, content (nzb), category
            if len(params) < 3:
                return {"error": {"code": -32602, "message": "Invalid parameters"}}
                
            nzbname = params[0]
            nzb_content = params[1]  # Ignorieren wir in unserer Implementierung
            category = params[2]
            
            # Priorität und andere Parameter sind optional
            priority = params[3] if len(params) > 3 else 0
            
            # In unserer Implementierung müssten wir hier die NZB parsen
            # und die Episode-URL extrahieren, aber wir emulieren das nur
            # und erstellen einen Dummy-Download
            
            download = Download(
                filename=nzbname,
                status="queued",
                created_at=datetime.utcnow(),
                source_url="http://example.com/dummy", # Wird später aktualisiert
                episode_id="unknown"
            )
            
            db.add(download)
            db.commit()
            db.refresh(download)
            
            return {
                "result": download.id
            }
            
        elif method == "editqueue":
            # Queue bearbeiten (z.B. löschen, pausieren, fortsetzen)
            # Parameter: command, editlist (IDs)
            if len(params) < 2:
                return {"error": {"code": -32602, "message": "Invalid parameters"}}
                
            command = params[0]
            edit_list = params[1]  # Liste von IDs
            
            # Nur 'delete' implementieren
            if command == "GroupDelete" or command == "HistoryDelete":
                for download_id in edit_list:
                    download = db.query(Download).filter_by(id=download_id).first()
                    if download:
                        download.status = "cancelled"
                        logger.info(f"Download {download_id} wurde gelöscht")
                        
                db.commit()
                return {"result": "OK"}
            
            return {"result": "OK"}
            
        elif method == "status":
            # Status-Informationen
            manager = DownloadManager(db)
            queue_status = manager.get_queue_status()
            
            return {
                "result": {
                    "DownloadRate": 0,  # Nicht verfügbar
                    "RemainingSizeLo": 0,
                    "RemainingSizeHi": 0,
                    "DownloadedSizeLo": 0,
                    "DownloadedSizeHi": 0,
                    "ArticleCacheLo": 0,
                    "ArticleCacheHi": 0,
                    "ServerStandBy": False,
                    "DownloadPaused": False,
                    "Download2Paused": False,
                    "PostPaused": False,
                    "ScanPaused": False,
                    "FreeDiskSpaceLo": 1000000,  # 1GB (Dummy-Wert)
                    "FreeDiskSpaceHi": 0,
                    "ServerTime": int(datetime.utcnow().timestamp()),
                    "ResumeTime": 0,
                    "RemainingSizeMB": 0,
                    "DownloadedSizeMB": 0,
                    "ArticleCacheMB": 0,
                    "ThreadCount": 1,
                    "ParJobCount": 0,
                    "PostJobCount": 0,
                    "UrlCount": queue_status["queued"] + queue_status["downloading"],
                    "UpTimeSec": 3600,  # 1 Stunde (Dummy-Wert)
                    "DownloadTimeSec": 0,
                    "ServerPaused": False,
                    "ServerQuotaReached": False,
                    "FreeDiskSpaceMB": 1000000,  # 1GB (Dummy-Wert)
                }
            }
        
        elif method == "pausedownload" or method == "pausepost":
            # Pause Funktionen (einfach OK zurückgeben)
            return {"result": "OK"}
            
        elif method == "resumedownload" or method == "resumepost":
            # Resume Funktionen (einfach OK zurückgeben)
            return {"result": "OK"}
            
        elif method == "config":
            # NZBGet Konfiguration - wichtig für Sonarr Test
            return {
                "result": [
                    # Wichtigste Einstellungen für Sonarr
                    {"Name": "Server.Port", "Value": "8000"},
                    {"Name": "Server.ApiKey", "Value": "pbarr_api_key"},
                    {"Name": "ControlIP", "Value": "0.0.0.0"},
                    {"Name": "ControlPort", "Value": "8000"},
                    {"Name": "SecureControl", "Value": "no"},
                    {"Name": "ControlUsername", "Value": ""},
                    {"Name": "ControlPassword", "Value": ""},
                    {"Name": "Category1.Name", "Value": "sonarr"},
                    {"Name": "Category1.DestDir", "Value": "/app/downloads/completed"},
                    {"Name": "Category2.Name", "Value": "tv"},
                    {"Name": "Category2.DestDir", "Value": "/app/downloads/completed"},
                    # Weitere Einstellungen
                    {"Name": "MainDir", "Value": "/app/downloads"},
                    {"Name": "DestDir", "Value": "/app/downloads/completed"},
                    {"Name": "InterDir", "Value": "/app/downloads/incomplete"},
                    {"Name": "TempDir", "Value": "/app/downloads/temp"},
                    {"Name": "WebDir", "Value": ""},
                    {"Name": "ConfigTemplate", "Value": ""},
                ]
            }
        
        else:
            # Unbekannte Methode - für Debugging ausgeben, aber keinen Fehler werfen
            logger.warning(f"Unbekannte NZBGet-Methode: {method}")
            
            # Bei Unbekannten Methoden leeres Ergebnis zurückgeben statt Fehler
            # Das verhindert, dass Sonarr den Test abbricht
            return {"result": []}
            
    except Exception as e:
        logger.error(f"NZBGet RPC Error: {str(e)}")
        return {"error": {"code": -32603, "message": f"Internal error: {str(e)}"}}
