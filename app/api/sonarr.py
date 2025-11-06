"""
Sonarr Custom Indexer & Download Client Integration
"""
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Request
from sqlalchemy.orm import Session
import logging
import httpx
from datetime import datetime

from app.database import get_db
from app.models.config import Config
from app.models.episode import Episode
from app import __version__


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sonarr", tags=["sonarr"])

def get_sonarr_config(db: Session):
    """Hole Sonarr Config aus DB"""
    sonarr_url = db.query(Config).filter_by(key="sonarr_url").first()
    sonarr_api_key = db.query(Config).filter_by(key="sonarr_api_key").first()
    
    return {
        "url": sonarr_url.value if sonarr_url else None,
        "api_key": sonarr_api_key.value if sonarr_api_key else None
    }

async def notify_sonarr(sonarr_config: dict, event_type: str, data: dict):
    """Benachrichtige Sonarr über Events"""
    if not sonarr_config["url"] or not sonarr_config["api_key"]:
        logger.warning("Sonarr not configured, skipping notification")
        return
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            payload = {
                "eventType": event_type,
                "data": data,
                "timestamp": datetime.utcnow().isoformat()
            }
            logger.debug(f"Sonarr Event: {event_type} - {data}")
    except Exception as e:
        logger.error(f"Sonarr notification failed: {e}")

@router.get("/config")
async def get_indexer_config():
    """Sonarr Config (zur Integrations-Validierung)"""
    return {
        "name": "PBArr",
        "implementation": "PBArr",
        "configContract": "PBArrSettings",
        "infoLink": "http://localhost:8000",
        "tags": ["mediathek", "german", "ard", "zdf"],
        "presets": []
    }

@router.post("/test")
async def test_connection(db: Session = Depends(get_db)):
    """Test Connection zu Sonarr"""
    sonarr_config = get_sonarr_config(db)
    
    if not sonarr_config["url"] or not sonarr_config["api_key"]:
        return {
            "success": False,
            "error": "Sonarr URL or API Key not configured"
        }
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{sonarr_config['url']}/api/v3/health",
                headers={"X-Api-Key": sonarr_config['api_key']}
            )
            
            if response.status_code == 200:
                logger.info("✓ Connected to Sonarr")
                return {"success": True, "sonarr": "connected"}
            else:
                logger.error(f"Sonarr connection failed: {response.status_code}")
                return {"success": False, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        logger.error(f"Sonarr test failed: {e}")
        return {"success": False, "error": str(e)}

@router.post("/grab")
async def grab_release(
    indexerId: int = Query(...),
    indexerPriority: int = Query(25),
    releaseTitle: str = Query(...),
    guid: str = Query(...),
    tvdbId: int = Query(...),
    season: int = Query(...),
    episodes: str = Query(...),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None
):
    """
    Sonarr ruft diesen Endpoint auf, wenn eine Release gegrabbt wird
    """
    
    try:
        logger.info(f"Sonarr Grab Request: {releaseTitle} (TVDB: {tvdbId}, S{season}E{episodes})")
        
        sonarr_config = get_sonarr_config(db)
        
        # Parse Episodes (können comma-separated sein: "1,2,3")
        ep_numbers = [int(e.strip()) for e in episodes.split(',')]
        
        # Finde Episodes in unserer DB
        for ep_num in ep_numbers:
            episode = db.query(Episode).filter(
                Episode.show_id == str(tvdbId),
                Episode.season == season,
                Episode.episode_number == ep_num,
                Episode.is_available == True
            ).first()
            
            if episode:
                # Episode gefunden - würde normalerweise heruntergeladen werden
                # Aber da wir jetzt direkt über Mediathek-Cacher laden, nur loggen
                logger.info(f"✓ Episode available for download: S{season}E{ep_num} - {releaseTitle}")
                logger.info(f"  Media URL: {episode.media_url or episode.source_url}")

                # Optional: Benachrichtige Sonarr
                if background_tasks:
                    background_tasks.add_task(
                        notify_sonarr,
                        sonarr_config,
                        "GrabSuccess",
                        {
                            "title": releaseTitle,
                            "indexer": "PBArr",
                            "message": "Episode queued for direct library download"
                        }
                    )
            else:
                logger.warning(f"Episode not found: S{season}E{ep_num} (TVDB: {tvdbId})")
        
        return {
            "success": True,
            "message": f"Grabbed {len(ep_numbers)} episode(s)",
            "episodes": ep_numbers
        }
    
    except Exception as e:
        logger.error(f"Grab error: {e}")
        return {
            "success": False,
            "error": str(e)
        }



@router.get("/version")
async def get_version():
    """Version für Sonarr"""
    return {
        "version": __version__,
        "name": "PBArr",
        "type": "indexer"
    }
