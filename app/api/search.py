from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from xml.etree import ElementTree as ET
from datetime import datetime

from app.database import get_db
from app.models import Show, Episode

router = APIRouter(prefix="/api", tags=["search"])

def build_newznab_rss(episodes: list) -> str:
    """Baut Newznab/RSS XML"""
    rss = ET.Element("rss")
    rss.set("version", "2.0")
    
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "PBArr - Newznab Feed"
    ET.SubElement(channel, "link").text = "http://localhost:8000"
    ET.SubElement(channel, "description").text = "Public Broadcasting Archive Indexer"
    
    for episode in episodes:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = f"{episode.title} S{episode.season:02d}E{episode.episode_number:02d}"
        ET.SubElement(item, "link").text = episode.media_url or episode.source_url
        ET.SubElement(item, "description").text = episode.description or ""
        ET.SubElement(item, "pubDate").text = episode.air_date.isoformat() if episode.air_date else ""
        
        # Newznab Extensions
        enclosure = ET.SubElement(item, "enclosure")
        enclosure.set("url", episode.media_url or episode.source_url)
        enclosure.set("type", "application/x-nzb")
    
    return ET.tostring(rss, encoding="unicode")

@router.get("/")
async def newznab_search(
    t: str = Query(..., description="Search type: tvsearch, movie"),
    tvdbid: str = Query(None, description="TVDB ID"),
    season: int = Query(None),
    ep: int = Query(None),
    db: Session = Depends(get_db)
):
    """Newznab API für Sonarr Integration"""
    
    if t != "tvsearch":
        return Response(content="<rss></rss>", media_type="application/rss+xml")
    
    if not tvdbid:
        return Response(content="<rss></rss>", media_type="application/rss+xml")
    
    # Finde Show
    show = db.query(Show).filter(Show.tvdb_id == tvdbid).first()
    if not show:
        return Response(content="<rss></rss>", media_type="application/rss+xml")
    
    # Finde Episodes
    query = db.query(Episode).filter(Episode.show_id == tvdbid)
    
    if season is not None:
        query = query.filter(Episode.season == season)
    
    if ep is not None:
        query = query.filter(Episode.episode_number == ep)
    
    episodes = query.filter(Episode.is_available == True).all()
    
    # Build RSS
    rss_content = build_newznab_rss(episodes)
    
    return Response(content=rss_content, media_type="application/rss+xml")

@router.get("/search")
async def search_shows(q: str = Query(...), db: Session = Depends(get_db)):
    """Suche nach Shows"""
    shows = db.query(Show).filter(Show.title.ilike(f"%{q}%")).limit(20).all()
    return {
        "query": q,
        "results": [
            {
                "tvdb_id": show.tvdb_id,
                "title": show.title,
                "source": show.source
            }
            for show in shows
        ]
    }
