from fastapi import APIRouter, Depends, Query, Request
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

# Newznab Namespace
NS = "http://www.newznab.com/DTD/2010/feeds/attributes/"

def build_caps_xml() -> str:
    """Baut Newznab Capabilities XML"""
    root = ET.Element("caps")

    server = ET.SubElement(root, "server")
    server.set("version", "1.0")
    server.set("title", "PBArr")
    server.set("strapline", "Public Broadcasting Archive")
    server.set("email", "")
    server.set("url", "http://localhost:8000")
    
    limits = ET.SubElement(root, "limits")
    limits.set("max", "100")
    limits.set("default", "100")
    
    registration = ET.SubElement(root, "registration")
    registration.set("available", "yes")
    registration.set("open", "no")
    
    searching = ET.SubElement(root, "searching")
    
    search = ET.SubElement(searching, "search")
    search.set("available", "yes")
    search.set("supportedParams", "q")
    
    tv_search = ET.SubElement(searching, "tv-search")
    tv_search.set("available", "yes")
    tv_search.set("supportedParams", "q,tvdbid,season,ep,imdbid")
    
    categories = ET.SubElement(root, "categories")
    
    tv_cat = ET.SubElement(categories, "category")
    tv_cat.set("id", "5000")
    tv_cat.set("name", "TV")
    tv_cat.set("description", "TV")
    
    tv_hd = ET.SubElement(tv_cat, "subcat")
    tv_hd.set("id", "5030")
    tv_hd.set("name", "TV/HD")
    tv_hd.set("description", "TV/HD")
    
    tv_sd = ET.SubElement(tv_cat, "subcat")
    tv_sd.set("id", "5040")
    tv_sd.set("name", "TV/SD")
    tv_sd.set("description", "TV/SD")
    
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_str += ET.tostring(root, encoding='unicode')
    return xml_str

def build_newznab_rss(episodes: list, total: int = 0) -> str:
    """Baut Newznab/RSS XML"""
    
    root = ET.Element("rss")
    root.set("version", "2.0")
    root.set("xmlns:newznab", NS)

    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = "PBArr"
    ET.SubElement(channel, "link").text = "http://localhost:8000"
    ET.SubElement(channel, "description").text = "PBArr - Public Broadcasting Archive"
    ET.SubElement(channel, "language").text = "de"
    
    # WICHTIG: Response Element mit Total Count
    response = ET.SubElement(channel, "{" + NS + "}response")
    response.set("offset", "0")
    response.set("total", str(max(total, len(episodes))))

    for episode in episodes:
        item = ET.SubElement(channel, "item")
        
        title_text = f"{episode.title} - S{episode.season:02d}E{episode.episode_number:02d}"
        ET.SubElement(item, "title").text = title_text
        
        ET.SubElement(item, "link").text = episode.media_url or episode.source_url or ""
        ET.SubElement(item, "guid").text = f"pbarr-{episode.id}"
        ET.SubElement(item, "pubDate").text = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
        ET.SubElement(item, "category").text = "TV/HD"
        
        desc = f"S{episode.season:02d}E{episode.episode_number:02d}"
        if episode.description:
            desc += f" - {episode.description[:100]}"
        ET.SubElement(item, "description").text = desc
        
        # Enclosure
        enclosure = ET.SubElement(item, "enclosure")
        enclosure.set("url", episode.media_url or episode.source_url or "")
        enclosure.set("length", "0")
        enclosure.set("type", "application/x-nzb")
        
        # Newznab Attributes
        attr_cat = ET.SubElement(item, "{" + NS + "}attr")
        attr_cat.set("name", "category")
        attr_cat.set("value", "5030")
        
        attr_cat2 = ET.SubElement(item, "{" + NS + "}attr")
        attr_cat2.set("name", "category")
        attr_cat2.set("value", "5000")

    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_str += ET.tostring(root, encoding='unicode')
    return xml_str

@router.get("/")
async def newznab_search(
    t: str = Query(None),
    q: str = Query(None),
    tvdbid: str = Query(None),
    season: int = Query(None),
    ep: int = Query(None),
    cat: str = Query(None),
    db: Session = Depends(get_db)
):
    """Newznab API"""

    logger.info(f"Newznab request: t={t}, tvdbid={tvdbid}, q={q}, cat={cat}")

    if t == "caps":
        xml = build_caps_xml()
        return Response(content=xml, media_type="application/rss+xml; charset=utf-8")

    if t == "tvsearch":
        logger.info(f"TV Search: tvdbid={tvdbid}, season={season}, ep={ep}")

        query = db.query(Episode)
        
        if tvdbid:
            query = query.filter(Episode.show_id == str(tvdbid))
        
        if season is not None:
            query = query.filter(Episode.season == season)
        
        if ep is not None:
            query = query.filter(Episode.episode_number == ep)

        episodes = query.filter(Episode.is_available == True).all()
        logger.info(f"Found {len(episodes)} episodes")

        # WICHTIG: Total count + episodes
        xml = build_newznab_rss(episodes, total=len(episodes))
        return Response(content=xml, media_type="application/rss+xml; charset=utf-8")

    # Default leere RSS mit Response Element
    empty = build_newznab_rss([], total=0)
    return Response(content=empty, media_type="application/rss+xml; charset=utf-8")
