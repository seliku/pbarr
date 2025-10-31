from fastapi import APIRouter, Query, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import or_
from datetime import datetime
import logging


from app.database import get_db
from app.models.watch_list import WatchList
from app.models.mediathek_cache import MediathekCache
from app.models.tvdb_cache import TVDBCache


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api", tags=["search"])


@router.get("/")
async def newznab_search(
    t: str = Query(None),
    q: str = Query(None),
    tvdbid: int = Query(None),
    season: int = Query(None),
    ep: int = Query(None),
    db: Session = Depends(get_db)
):
    """
    Newznab API Endpoint
    
    Sonarr ruft auf:
    GET /api/?t=tvsearch&tvdbid=298954&season=11&ep=1
    
    Flow:
    1. Update watch_list (mark as accessed)
    2. Search mediathek_cache
    3. Return Newznab XML
    """
    
    try:
        logger.info(f"Search: t={t}, tvdbid={tvdbid}, season={season}, ep={ep}")
        
        # Validiere Request
        if t != "tvsearch":
            return _newznab_error("Invalid search type")
        
        if not tvdbid:
            return _newznab_error("Missing tvdbid")
        
        tvdb_id_str = str(tvdbid)
        
        # Step 1: Update oder Create Watch-List Eintrag
        watch = db.query(WatchList).filter_by(tvdb_id=tvdb_id_str).first()
        
        if watch:
            # Update last_accessed
            watch.last_accessed = datetime.utcnow()
            db.commit()
            logger.info(f"✓ Watch-list updated: TVDB {tvdb_id_str}")
        else:
            # Neue Serie in Watch-List
            # Hole Show-Name von TVDB Cache
            tvdb_cache = db.query(TVDBCache).filter_by(tvdb_id=tvdb_id_str).first()
            show_name = tvdb_cache.show_name if tvdb_cache else f"Show_{tvdb_id_str}"
            
            watch = WatchList(
                tvdb_id=tvdb_id_str,
                show_name=show_name,
                last_accessed=datetime.utcnow()
            )
            db.add(watch)
            db.commit()
            logger.info(f"✓ New watch-list entry: {show_name} (TVDB {tvdb_id_str})")
        
        # Step 2: Search Cache
        results = []
        
        if season is not None and ep is not None:
            # Episode-spezifische Suche
            cache_results = db.query(MediathekCache).filter(
                MediathekCache.tvdb_id == tvdb_id_str,
                MediathekCache.season == season,
                MediathekCache.episode == ep,
                MediathekCache.expires_at > datetime.utcnow()
            ).all()
            
            logger.info(f"Found {len(cache_results)} cache results for S{season:02d}E{ep:02d}")
            results = cache_results
        
        else:
            # Alle Episoden dieser Serie im Cache
            cache_results = db.query(MediathekCache).filter(
                MediathekCache.tvdb_id == tvdb_id_str,
                MediathekCache.expires_at > datetime.utcnow()
            ).all()
            
            logger.info(f"Found {len(cache_results)} cache results total")
            results = cache_results
        
        if not results:
            logger.info("No cache results, returning empty")
            return _newznab_rss(tvdb_id_str, [])
        
        # Step 3: Build Newznab XML
        return _newznab_rss(tvdb_id_str, results)
    
    except Exception as e:
        logger.error(f"Search error: {e}", exc_info=True)
        return _newznab_error(str(e))


def _newznab_rss(tvdb_id: str, cache_results):
    """Build Newznab RSS Response"""
    
    items_xml = ""
    
    for cache in cache_results:
        item_xml = f"""
    <item>
        <title>{cache.episode_title}</title>
        <link>{cache.media_url}</link>
        <description>S{cache.season:02d}E{cache.episode:02d} - {cache.episode_title}</description>
        <category>5000</category>
        <pubDate>{cache.created_at.strftime('%a, %d %b %Y %H:%M:%S %z')}</pubDate>
        <enclosure url="{cache.media_url}" type="application/x-nzb" />
        <newznab:attr name="tvdbid" value="{tvdb_id}" />
        <newznab:attr name="season" value="{cache.season}" />
        <newznab:attr name="episode" value="{cache.episode}" />
    </item>"""
        items_xml += item_xml
    
    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:newznab="http://www.newzbin.com/DTD/2003/nzb">
    <channel>
        <title>PBArr - Mediathek Search Results</title>
        <link>http://pbarray.local/</link>
        <description>Newznab API für deutschsprachige Mediatheken</description>
        <language>de</language>
        {items_xml}
    </channel>
</rss>"""
    
    return Response(content=rss, media_type="application/rss+xml")


def _newznab_error(message: str):
    """Newznab Error Response"""
    error_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
    <channel>
        <error code="200">{message}</error>
    </channel>
</rss>"""
    
    return Response(content=error_xml, media_type="application/rss+xml")
