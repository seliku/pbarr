from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from xml.etree import ElementTree as ET
from datetime import datetime
import logging

from app.database import get_db
from app.models.show import Show
from app.models.episode import Episode

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["search"])

def build_newznab_rss(episodes: list, tvdb_id: str) -> str:
    """Baut Newznab/RSS XML für Sonarr"""
    rss = ET.Element("rss")
    rss.set("version", "2.0")
    rss.set("xmlns:atom", "http://www.w3.org/2005/Atom")
    rss.set("xmlns:newznab", "http://www.newzbin.com/DTD/2003/newzbin.dtd")

    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "PBArr - Newznab Feed"
    ET.SubElement(channel, "link").text = "http://localhost:8000"
    ET.SubElement(channel, "description").text = "Public Broadcasting Archive Indexer"
    ET.SubElement(channel, "language").text = "de"

    for episode in episodes:
        item = ET.SubElement(channel, "item")
        
        # Title Format für Sonarr: "Show Title - SxxExx"
        title_text = f"{episode.title} - S{episode.season:02d}E{episode.episode_number:02d}"
        ET.SubElement(item, "title").text = title_text
        
        ET.SubElement(item, "link").text = episode.media_url or episode.source_url or ""
        ET.SubElement(item, "description").text = episode.description or ""
        
        if episode.air_date:
            ET.SubElement(item, "pubDate").text = episode.air_date.strftime("%a, %d %b %Y %H:%M:%S +0000")
        
        # Newznab Extensions
        newznab_attr = ET.SubElement(item, "newznab:attr")
        newznab_attr.set("name", "tvdbid")
        newznab_attr.set("value", str(tvdb_id))
        
        newznab_attr2 = ET.SubElement(item, "newznab:attr")
        newznab_attr2.set("name", "season")
        newznab_attr2.set("value", str(episode.season))
        
        newznab_attr3 = ET.SubElement(item, "newznab:attr")
        newznab_attr3.set("name", "episode")
        newznab_attr3.set("value", str(episode.episode_number))
        
        # Enclosure für Download-URL
        enclosure = ET.SubElement(item, "enclosure")
        enclosure.set("url", episode.media_url or episode.source_url or "")
        enclosure.set("type", "application/x-nzb")
        enclosure.set("length", "0")

    return ET.tostring(rss, encoding="unicode")

@router.get("/")
async def newznab_search(
    t: str = Query(..., description="Search type: tvsearch"),
    tvdbid: str = Query(None, description="TVDB ID"),
    season: int = Query(None),
    ep: int = Query(None),
    db: Session = Depends(get_db)
):
    """Newznab API für Sonarr Integration"""

    logger.info(f"Newznab search: t={t}, tvdbid={tvdbid}, season={season}, ep={ep}")

    if t != "tvsearch":
        logger.warning(f"Unsupported search type: {t}")
        return Response(content="<rss><channel></channel></rss>", media_type="application/rss+xml")

    if not tvdbid:
        logger.warning("Missing tvdbid parameter")
        return Response(content="<rss><channel></channel></rss>", media_type="application/rss+xml")

    # Finde Show
    show = db.query(Show).filter(Show.tvdb_id == str(tvdbid)).first()
    if not show:
        logger.info(f"Show not found: TVDB {tvdbid}")
        return Response(content="<rss><channel></channel></rss>", media_type="application/rss+xml")

    logger.info(f"Found show: {show.title}")

    # Finde Episodes
    query = db.query(Episode).filter(Episode.show_id == str(tvdbid))

    if season is not None:
        query = query.filter(Episode.season == season)
        logger.info(f"Filtering season: {season}")

    if ep is not None:
        query = query.filter(Episode.episode_number == ep)
        logger.info(f"Filtering episode: {ep}")

    episodes = query.filter(Episode.is_available == True).all()

    logger.info(f"Found {len(episodes)} episodes")

    # Build RSS
    rss_content = build_newznab_rss(episodes, tvdbid)

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
