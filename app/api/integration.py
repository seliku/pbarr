from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
import logging
import aiohttp
from xml.etree import ElementTree as ET

from app.database import get_db
from app.models.config import Config
from app.models.show import Show
from app.models.episode import Episode
from app.services.tvdb_client import TVDBClient
from app.services.episode_matcher import EpisodeMatcher

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integration", tags=["integration"])

class SonarrIntegrationRequest(BaseModel):
    tvdb_id: int
    show_name: str

@router.post("/sonarr-integration")
async def sonarr_integration(request: SonarrIntegrationRequest, db: Session = Depends(get_db)):
    """End-to-End: TVDB ID → MediathekViewWeb → Match → Save to DB"""

    try:
        tvdb_key_config = db.query(Config).filter_by(key="tvdb_api_key").first()
        if not tvdb_key_config or not tvdb_key_config.value:
            raise HTTPException(status_code=400, detail="TVDB API key not configured")

        tvdb_client = TVDBClient(tvdb_key_config.value, db=db)

        logger.info(f"Step 1: Fetching TVDB #{request.tvdb_id}")
        tvdb_episodes = await tvdb_client.get_episodes(request.tvdb_id)
        if not tvdb_episodes:
            raise HTTPException(status_code=404, detail=f"No episodes in TVDB #{request.tvdb_id}")

        logger.info(f"✓ Got {len(tvdb_episodes)} TVDB episodes")

        # Speichere Show
        show = db.query(Show).filter_by(tvdb_id=str(request.tvdb_id)).first()
        if not show:
            show = Show(
                tvdb_id=str(request.tvdb_id),
                title=request.show_name,
                source="mediathekviewweb",
                language="de"
            )
            db.add(show)
            db.commit()
            logger.info(f"✓ Show created: {request.show_name}")

        logger.info(f"Step 2: Searching MediathekViewWeb for: {request.show_name}")

        feed_url = f"https://mediathekviewweb.de/feed?query=!ard%20%23{request.show_name.replace(' ', '%2C')}%20%3E20"

        mediathek_episodes = []
        async with aiohttp.ClientSession() as session:
            async with session.get(feed_url, timeout=15) as resp:
                if resp.status == 200:
                    content = await resp.text()
                    try:
                        root = ET.fromstring(content)
                        for item in root.findall('.//item'):
                            title = item.findtext('title', '')
                            link = item.findtext('link', '')
                            pub_date = item.findtext('pubDate', '')
                            if link:
                                mediathek_episodes.append({
                                    'title': title,
                                    'description': item.findtext('description', '')[:500],
                                    'link': link,
                                    'pub_date': pub_date,
                                })
                    except ET.ParseError:
                        pass

        if not mediathek_episodes:
            raise HTTPException(status_code=404, detail="No episodes in MediathekViewWeb")

        logger.info(f"✓ Found {len(mediathek_episodes)} MediathekViewWeb episodes")

        logger.info(f"Step 3: Matching episodes...")

        matcher = EpisodeMatcher(db)
        matched = []
        saved_episodes = []

        # ✅ Create lookup dict für schnelleren TVDB Episode Zugriff
        tvdb_lookup = {}
        for tvdb_ep in tvdb_episodes:
            key = (tvdb_ep.get('season'), tvdb_ep.get('episode'))
            tvdb_lookup[key] = tvdb_ep

        for mediathek_ep in mediathek_episodes:
            result = matcher.match_episode(mediathek_ep, tvdb_episodes)
            if result:
                # ✅ FIX: Hole Episode-Details aus TVDB Lookup
                tvdb_key = (result.season, result.episode)
                tvdb_ep_data = tvdb_lookup.get(tvdb_key, {})
                
                episode = Episode(
                    show_id=str(request.tvdb_id),
                    season=result.season,
                    episode_number=result.episode,
                    title=tvdb_ep_data.get('name', 'Unknown'),
                    description=tvdb_ep_data.get('overview', ''),
                    air_date=tvdb_ep_data.get('aired'),
                    source_url=mediathek_ep['link'],
                    media_url=mediathek_ep['link'],
                    source="mediathekviewweb",
                    language="de",
                    match_confidence=result.confidence,
                    match_type=result.match_type,
                    mediathek_title=mediathek_ep.get('title'),
                    is_available=True
                )
                db.add(episode)
                db.commit()
                
                matched.append({
                    "id": episode.id,
                    "mediathek_title": mediathek_ep.get("title"),
                    "tvdb_season": result.season,
                    "tvdb_episode": result.episode,
                    "tvdb_title": tvdb_ep_data.get('name', 'Unknown'),
                    "confidence": round(result.confidence, 2),
                    "match_type": result.match_type,
                    "link": mediathek_ep['link'],
                })
                saved_episodes.append(episode)

        logger.info(f"✓ Matched and saved {len(matched)} episodes")

        return {
            "success": True,
            "tvdb_id": request.tvdb_id,
            "show_name": request.show_name,
            "tvdb_episodes": len(tvdb_episodes),
            "mediathek_episodes": len(mediathek_episodes),
            "matched": len(matched),
            "episodes": matched
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/extract-download-url")
async def extract_download_url(episode_url: str = Query(...)):
    """Download URL via yt-dlp"""
    try:
        import subprocess
        cmd = ['yt-dlp', '-f', 'best', '-g', episode_url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            url = result.stdout.strip().split('\n')[0]
            return {"success": True, "download_url": url}
        else:
            raise HTTPException(status_code=500, detail="yt-dlp failed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
