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


def get_category_by_quality(quality: str) -> str:
    """Bestimme Kategorie basierend auf Qualität"""
    if quality and "1080" in quality:
        return "5030"  # TV/HD
    elif quality and "720" in quality:
        return "5030"  # TV/HD
    else:
        return "5040"  # TV/SD


def build_caps_xml(request_url: str = "http://localhost:8000") -> str:
    """Baut Newznab Capabilities XML"""
    root = ET.Element("caps")

    server = ET.SubElement(root, "server")
    server.set("version", "1.0")
    server.set("title", "PBArr")
    server.set("strapline", "Public Broadcasting Archive")
    server.set("email", "")
    server.set("url", request_url)
    
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
    """Baut Newznab/RSS XML - OHNE namespace register"""
    
    # Manuell bauen statt ElementTree (verhindert ns0 Bug)
    xml_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/">',
        '<channel>',
        '<title>PBArr</title>',
        '<link>http://localhost:8000</link>',
        '<description>PBArr - Public Broadcasting Archive</description>',
        '<language>de</language>',
        f'<newznab:response offset="0" total="{max(total, len(episodes))}" />',
    ]
    
    for episode in episodes:
        category = get_category_by_quality(episode.quality)
        category_name = "TV/HD" if category == "5030" else "TV/SD"
        desc = f"S{episode.season:02d}E{episode.episode_number:02d}"
        if episode.description:
            desc += f" - {episode.description[:100]}"
        
        xml_parts.append(f'''<item>
<title>{episode.title} - S{episode.season:02d}E{episode.episode_number:02d}</title>
<link>{episode.media_url or episode.source_url or ""}</link>
<guid>pbarr-{episode.id}</guid>
<pubDate>{datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")}</pubDate>
<category>{category_name}</category>
<description>{desc}</description>
<enclosure url="{episode.media_url or episode.source_url or ""}" length="0" type="application/x-nzb" />
<newznab:attr name="category" value="{category}" />
</item>''')
    
    xml_parts.extend([
        '</channel>',
        '</rss>'
    ])
    
    return '\n'.join(xml_parts)


@router.get("/")
async def newznab_search(
    t: str = Query(None),
    q: str = Query(None),
    tvdbid: str = Query(None),
    season: int = Query(None),
    ep: int = Query(None),
    cat: str = Query(None),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Newznab API"""

    request_url = f"{request.url.scheme}://{request.url.netloc}"
    logger.info(f"Newznab request: t={t}, tvdbid={tvdbid}, q={q}, cat={cat}, url={request_url}")

    if t == "caps":
        xml = build_caps_xml(request_url)
        return Response(content=xml, media_type="application/rss+xml; charset=utf-8")

    if t == "tvsearch":
        logger.info(f"TV Search: tvdbid={tvdbid}, season={season}, ep={ep}, cat={cat}")

        query = db.query(Episode)
        
        if tvdbid:
            logger.info(f"Filtering by tvdbid: {tvdbid}")
            query = query.filter(Episode.show_id == str(tvdbid))
        
        if season is not None:
            query = query.filter(Episode.season == season)
        
        if ep is not None:
            query = query.filter(Episode.episode_number == ep)

        if cat:
            cat_list = [c.strip() for c in cat.split(",")]
            logger.info(f"Filtering by categories: {cat_list}")
            
            episodes = query.filter(Episode.is_available == True).all()
            
            filtered_episodes = []
            for ep_item in episodes:
                ep_cat = get_category_by_quality(ep_item.quality)
                if ep_cat in cat_list:
                    filtered_episodes.append(ep_item)
            
            episodes = filtered_episodes
        else:
            episodes = query.filter(Episode.is_available == True).all()

        logger.info(f"Found {len(episodes)} episodes matching criteria")

        xml = build_newznab_rss(episodes, total=len(episodes))
        return Response(content=xml, media_type="application/rss+xml; charset=utf-8")

    empty = build_newznab_rss([], total=0)
    return Response(content=empty, media_type="application/rss+xml; charset=utf-8")
