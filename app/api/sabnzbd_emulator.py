from fastapi import APIRouter, Request, Depends, Response, Query
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Dict, List, Any, Optional
import logging
import json

from app.database import get_db
from app.models.download import Download
from app.services.download_manager import DownloadManager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["sabnzbd"])

# SABnzbd Status-Mapping
SABNZBD_STATUS_MAP = {
    "queued": "Queued",
    "downloading": "Downloading",
    "completed": "Completed", 
    "failed": "Failed",
    "cancelled": "Deleted",
}

# Standard-Kategorien die IMMER verfügbar sind
DEFAULT_CATEGORIES = {
    "tv-sonarr": {"priority": 0, "pp": 3, "name": "tv-sonarr"},  # An erster Stelle, da diese in Sonarr konfiguriert ist
    "sonarr": {"priority": 0, "pp": 3, "name": "sonarr"},
    "tv": {"priority": 0, "pp": 3, "name": "tv"},
    "default": {"priority": 0, "pp": 3, "name": "default"},
    "series": {"priority": 0, "pp": 3, "name": "series"},
    "tv-hd": {"priority": 0, "pp": 3, "name": "tv-hd"},
    "tv-sd": {"priority": 0, "pp": 3, "name": "tv-sd"},
    "tv-uhd": {"priority": 0, "pp": 3, "name": "tv-uhd"},
    "*": {"priority": 0, "pp": 3, "name": "*"}
}


def format_queue_item(download: Download) -> Dict[str, Any]:
    """Format für SABnzbd Queue Items"""
    return {
        "id": str(download.id),
        "status": SABNZBD_STATUS_MAP.get(download.status, "Unknown"),
        "filename": download.filename,
        "cat": "tv-sonarr",
        "priority": "0",
        "size": "0",
        "sizeleft": "0",
        "timeleft": "0:00:00",
        "mb": "0",
        "mbmissing": "0",
        "percentage": download.progress or 0,
        "nzo_id": str(download.id),
        "unpackopts": "3",
        "script": "",
        "has_rating": False,
        "avg_age": "0d"
    }


def format_history_item(download: Download) -> Dict[str, Any]:
    """Format für SABnzbd History Items"""
    return {
        "id": str(download.id),
        "status": SABNZBD_STATUS_MAP.get(download.status, "Unknown"),
        "name": download.filename,
        "nzb_name": download.filename,
        "category": "tv-sonarr",
        "nzo_id": str(download.id),
        "download_time": (
            int((download.completed_at - download.started_at).total_seconds())
            if download.completed_at and download.started_at 
            else 0
        ),
        "size": "0",
        "bytes": 0,
        "completed": download.completed_at.strftime("%Y-%m-%d %H:%M:%S") if download.completed_at else "",
        "script": "",
        "stage_log": [{"name": "Download", "status": "Completed"}]
    }


@router.get("/sabnzbd/api")
async def sab_api_get(
    mode: str = Query(None),
    name: str = Query(None),
    nzbname: str = Query(None),
    apikey: str = Query(None),
    output: str = Query("json"),
    nzo_id: str = Query(None),
    value: str = Query(None),
    cat: str = Query(None),  # Kategorie-Parameter hinzugefügt
    db: Session = Depends(get_db)
):
    """
    Emuliert die SABnzbd HTTP API
    """
    # ALLE Parameter loggen für Debug
    all_params = {
        "mode": mode, "cat": cat, "name": name, 
        "apikey": apikey, "nzo_id": nzo_id, "value": value
    }
    logger.info(f"SABnzbd API Call: {all_params}")
    
        # Wenn cat parameter übergeben wird - prüfen und akzeptieren
        if cat:
            logger.info(f"Kategorie-Parameter empfangen: {cat}")
            if cat not in DEFAULT_CATEGORIES:
                logger.warning(f"Unknown category: {cat}, aber wir akzeptieren sie trotzdem")
            # Wir akzeptieren die Kategorie in jedem Fall, um Sonarr zufriedenzustellen
    
    try:
        response = {
            "status": True,
            "error": None,
            "version": "3.5.0"  # Ursprüngliche Version
        }
        
        if mode == "version":
            response["version"] = "3.5.0"
            
        elif mode == "get_cats" or mode == "get_cat_list":
            # KRITISCH: Diese Kategorien MÜSSEN vorhanden sein!
            
            # Alternative Struktur für die Kategorieantwort testen
            # Formatierung basierend auf der SABnzbd API-Dokumentation
            categories_list = list(DEFAULT_CATEGORIES.keys())
            response["categories"] = categories_list
            logger.debug(f"Returning categories as list: {categories_list}")
            
        elif mode == "get_scripts":
            response["scripts"] = []
            
        elif mode == "get_categories":
            response["categories"] = DEFAULT_CATEGORIES
            logger.debug(f"Returning categories: {list(DEFAULT_CATEGORIES.keys())}")
            
        elif mode == "get_config":
            response["config"] = {
                "misc": {
                    "complete_dir": "/app/downloads/completed",
                    "download_dir": "/app/downloads/incomplete",
                    "host": "0.0.0.0",
                    "port": "8000",
                    "api_key": "pbarr_api_key",
                    "enable_api_key": "1",
                    "username": "",
                    "password": ""
                }
            }
            
        elif mode == "queue":
            queue = db.query(Download).filter(
                Download.status.in_(["queued", "downloading"])
            ).order_by(Download.created_at.desc()).all()
            
            queue_items = [format_queue_item(item) for item in queue]
            manager = DownloadManager(db)
            queue_status = manager.get_queue_status()
            
            response["queue"] = {
                "slots": queue_items,
                "paused": False,
                "speedlimit": "0",
                "speed": "0",
                "mbleft": "0",
                "mb": "0",
                "kbpersec": "0",
                "timeleft": "0:00:00",
                "status": "Downloading" if queue_status["downloading"] > 0 else "Idle",
                "size": "0",
                "sizeleft": "0",
                "noofslots": len(queue_items),
                "categories": list(DEFAULT_CATEGORIES.keys()),
                "scripts": []
            }
            
        elif mode == "history":
            history = db.query(Download).filter(
                Download.status.in_(["completed", "failed", "cancelled"])
            ).order_by(Download.created_at.desc()).all()
            
            history_items = [format_history_item(item) for item in history]
            
            response["history"] = {
                "slots": history_items,
                "noofslots": len(history_items),
                "max_line_pars": 0,
                "total_size": "0",
                "week_size": "0",
                "month_size": "0"
            }
            
        elif mode == "addurl":
            file_name = name or nzbname or "Unknown"
            category_used = cat or "tv-sonarr"  # Kategorie aus Request oder Default
            
            logger.info(f"Download mit Kategorie: {category_used}")
            
            download = Download(
                filename=file_name,
                status="queued",
                created_at=datetime.utcnow(),
                source_url="http://example.com/dummy",
                episode_id="unknown"
                # Kategorie kann nicht gespeichert werden, da nicht im Modell
                # aber wir nehmen sie entgegen und loggen sie
            )
            
            db.add(download)
            db.commit()
            db.refresh(download)
            
            response["nzo_ids"] = [str(download.id)]
            logger.info(f"Download hinzugefügt: {file_name} (ID: {download.id})")
            
        elif mode == "delete":
            if nzo_id:
                download = db.query(Download).filter_by(id=int(nzo_id)).first()
                if download:
                    download.status = "cancelled"
                    db.commit()
                    logger.info(f"Download {nzo_id} wurde gelöscht")
            response["status"] = True
            
        elif mode == "pause":
            response["status"] = True
            
        elif mode == "resume":
            response["status"] = True
            
        elif mode == "qstatus":
            manager = DownloadManager(db)
            queue_status = manager.get_queue_status()
            
            response["state"] = "Downloading" if queue_status["downloading"] > 0 else "Idle"
            response["paused"] = False
            response["speed"] = 0
            response["mb"] = "0"
            response["mbleft"] = "0"
            response["diskspace1"] = "1000"
            response["diskspace2"] = "500"
            response["diskspacetotal1"] = "2000"
            response["diskspacetotal2"] = "1000"
            response["timeleft"] = "0:00:00"
            response["loadavg"] = "0.00"
            response["jobs"] = queue_status["queued"] + queue_status["downloading"]
            response["noofslots"] = response["jobs"]
            
        elif mode == "set_priority" or mode == "change_cat" or mode == "change_script":
            response["status"] = True
            
        else:
            logger.warning(f"Unbekannter SABnzbd-Modus: {mode}")
            response["status"] = True
        
        if output == "xml":
            return Response(
                content=f"<result>{json.dumps(response)}</result>",
                media_type="application/xml"
            )
        else:
            return response
            
    except Exception as e:
        logger.error(f"SABnzbd API Error: {str(e)}", exc_info=True)
        return {
            "status": False,
            "error": str(e),
            "version": "3.5.0"
        }


@router.post("/sabnzbd/api")
async def sab_api_post(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    POST-Version des SABnzbd API-Endpunkts (für Sonarr-Kompatibilität)
    """
    form_data = await request.form()
    query_params = dict(form_data)
    
    mode = query_params.get("mode")
    name = query_params.get("name")
    nzbname = query_params.get("nzbname")
    apikey = query_params.get("apikey")
    output = query_params.get("output", "json")
    nzo_id = query_params.get("nzo_id")
    value = query_params.get("value")
    
    cat = query_params.get("cat")  # Kategorie-Parameter extrahieren
    
    # ALLE Parameter loggen für Debug
    all_params = {
        "mode": mode, "cat": cat, "name": name, 
        "apikey": apikey, "nzo_id": nzo_id, "value": value
    }
    logger.info(f"SABnzbd API POST Call: {all_params}")
    
        # Wenn cat parameter übergeben wird - prüfen und akzeptieren
        if cat:
            logger.info(f"Kategorie-Parameter empfangen (POST): {cat}")
            if cat not in DEFAULT_CATEGORIES:
                logger.warning(f"Unknown category (POST): {cat}, aber wir akzeptieren sie trotzdem")
            # Wir akzeptieren die Kategorie in jedem Fall, um Sonarr zufriedenzustellen
    
    try:
        response = {
            "status": True,
            "error": None,
            "version": "3.5.0"  # Ursprüngliche Version
        }
        
        if mode == "version":
            response["version"] = "3.5.0"
        
        elif mode == "auth":
            response["auth"] = True
            
        elif mode == "get_cats" or mode == "get_cat_list":
            # Alternative Struktur für die Kategorieantwort testen
            categories_list = list(DEFAULT_CATEGORIES.keys())
            response["categories"] = categories_list
            logger.debug(f"Returning categories as list (POST): {categories_list}")
        
        elif mode == "get_scripts":
            response["scripts"] = []
        
        elif mode == "get_categories":
            response["categories"] = DEFAULT_CATEGORIES
            logger.debug(f"Returning categories (POST): {list(DEFAULT_CATEGORIES.keys())}")
        
        elif mode == "get_config":
            response["config"] = {
                "misc": {
                    "complete_dir": "/app/downloads/completed",
                    "download_dir": "/app/downloads/incomplete",
                    "host": "0.0.0.0",
                    "port": "8000",
                    "api_key": "pbarr_api_key",
                    "enable_api_key": "1",
                    "username": "",
                    "password": ""
                }
            }
        
        elif mode == "queue":
            queue = db.query(Download).filter(
                Download.status.in_(["queued", "downloading"])
            ).order_by(Download.created_at.desc()).all()
            
            queue_items = [format_queue_item(item) for item in queue]
            manager = DownloadManager(db)
            queue_status = manager.get_queue_status()
            
            response["queue"] = {
                "slots": queue_items,
                "paused": False,
                "speedlimit": "0",
                "speed": "0",
                "mbleft": "0",
                "mb": "0",
                "kbpersec": "0",
                "timeleft": "0:00:00",
                "status": "Downloading" if queue_status["downloading"] > 0 else "Idle",
                "size": "0",
                "sizeleft": "0",
                "noofslots": len(queue_items),
                "categories": list(DEFAULT_CATEGORIES.keys()),
                "scripts": []
            }
        
        elif mode == "history":
            history = db.query(Download).filter(
                Download.status.in_(["completed", "failed", "cancelled"])
            ).order_by(Download.created_at.desc()).all()
            
            history_items = [format_history_item(item) for item in history]
            
            response["history"] = {
                "slots": history_items,
                "noofslots": len(history_items),
                "max_line_pars": 0,
                "total_size": "0",
                "week_size": "0",
                "month_size": "0"
            }
        
        elif mode == "addurl":
            file_name = name or nzbname or "Unknown"
            category_used = cat or "tv-sonarr"  # Kategorie aus Request oder Default
            
            logger.info(f"Download mit Kategorie (POST): {category_used}")
            
            download = Download(
                filename=file_name,
                status="queued",
                created_at=datetime.utcnow(),
                source_url="http://example.com/dummy",
                episode_id="unknown"
                # Kategorie kann nicht gespeichert werden, da nicht im Modell
                # aber wir nehmen sie entgegen und loggen sie
            )
            
            db.add(download)
            db.commit()
            db.refresh(download)
            
            response["nzo_ids"] = [str(download.id)]
            logger.info(f"Download hinzugefügt: {file_name} (ID: {download.id})")
        
        elif mode == "delete":
            if nzo_id:
                download = db.query(Download).filter_by(id=int(nzo_id)).first()
                if download:
                    download.status = "cancelled"
                    db.commit()
                    logger.info(f"Download {nzo_id} wurde gelöscht")
            
            response["status"] = True
        
        elif mode == "pause" or mode == "resume":
            response["status"] = True
        
        elif mode == "qstatus":
            manager = DownloadManager(db)
            queue_status = manager.get_queue_status()
            
            response["state"] = "Downloading" if queue_status["downloading"] > 0 else "Idle"
            response["paused"] = False
            response["speed"] = 0
            response["mb"] = "0"
            response["mbleft"] = "0"
            response["diskspace1"] = "1000"
            response["diskspacetotal1"] = "2000"
            response["timeleft"] = "0:00:00"
            response["loadavg"] = "0.00"
            response["jobs"] = queue_status["queued"] + queue_status["downloading"]
            response["noofslots"] = response["jobs"]
        
        elif mode == "set_priority" or mode == "change_cat" or mode == "change_script":
            response["status"] = True
        
        else:
            logger.warning(f"Unbekannter SABnzbd-Modus: {mode}")
            response["status"] = True
        
        if output == "xml":
            return Response(
                content=f"<result>{json.dumps(response)}</result>",
                media_type="application/xml"
            )
        else:
            return response
    
    except Exception as e:
        logger.error(f"SABnzbd API Error (POST): {str(e)}", exc_info=True)
        return {
            "status": False,
            "error": str(e),
            "version": "3.5.0"
        }
