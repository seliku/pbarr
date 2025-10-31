from fastapi import APIRouter, Query, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Dict
import logging

from app.database import get_db
from app.models.watch_list import WatchList
from app.models.mediathek_cache import MediathekCache
from app.models.tvdb_cache import TVDBCache

logger = logging.getLogger(__name__)

router = APIRouter(tags=["search"])


class DummyCache:
    """Dummy object for Sonarr setup test"""
    def __init__(self):
        self.media_url = 'http://example.com/test.mp4'
        self.episode_title = 'Test Episode'
        self.quality = '720p'
        self.season = 1
        self.episode = 1
        self.mediathek_title = 'Test Show'
        self.created_at = datetime.utcnow()


@router.get("/api")
async def newznab_search(
    t: str = Query(None),
    q: str = Query(None),
    tvdbid: int = Query(None),
    season: int = Query(None),
    ep: int = Query(None),
    cat: str = Query(None),
    extended: int = Query(None),
    offset: int = Query(0),
    limit: int = Query(100),
    db: Session = Depends(get_db)
):
    """Newznab API Endpoint"""
    
    try:
        logger.info(f"Search: t={t}, tvdbid={tvdbid}, season={season}, ep={ep}, cat={cat}")
        
        # Parse requested categories if provided
        requested_cats = []
        if cat:
            requested_cats = cat.split(',')
        
        # Caps request
        if t == "caps":
            return _newznab_caps()
        
        if t != "tvsearch":
            return _newznab_rss("", [])
        
        # Ohne tvdbid = Sonarr-Test, aber mit Test-Daten damit Kategorien validiert werden
        if not tvdbid:
            logger.debug("No tvdbid - returning test result for Sonarr setup validation")
            return _newznab_rss("0", [DummyCache()], requested_cats)
        
        tvdb_id_str = str(tvdbid)
        
        # Update oder Create Watch-List
        watch = db.query(WatchList).filter_by(tvdb_id=tvdb_id_str).first()
        
        if watch:
            watch.last_accessed = datetime.utcnow()
            db.commit()
        else:
            tvdb_cache = db.query(TVDBCache).filter_by(tvdb_id=tvdb_id_str).first()
            show_name = tvdb_cache.show_name if tvdb_cache else f"Show_{tvdb_id_str}"
            
            watch = WatchList(
                tvdb_id=tvdb_id_str,
                show_name=show_name,
                last_accessed=datetime.utcnow()
            )
            db.add(watch)
            db.commit()
            logger.info(f"✓ New watch-list entry: {show_name}")
        
        # Search Cache
        results = []
        
        if season is not None and ep is not None:
            cache_results = db.query(MediathekCache).filter(
                MediathekCache.tvdb_id == tvdb_id_str,
                MediathekCache.season == season,
                MediathekCache.episode == ep,
                MediathekCache.expires_at > datetime.utcnow()
            ).all()
            
            logger.info(f"Found {len(cache_results)} cache results for S{season:02d}E{ep:02d}")
            results = cache_results
        else:
            cache_results = db.query(MediathekCache).filter(
                MediathekCache.tvdb_id == tvdb_id_str,
                MediathekCache.expires_at > datetime.utcnow()
            ).all()
            
            logger.info(f"Found {len(cache_results)} cache results total")
            results = cache_results
        
        # Pass requested categories to the RSS generator
        return _newznab_rss(tvdb_id_str, results, requested_cats)
    
    except Exception as e:
        logger.error(f"Search error: {e}", exc_info=True)
        return _newznab_rss("", [])


# Custom XML response class
class XMLResponse(Response):
    media_type = "application/xml"


def _get_categories(quality: str) -> List[str]:
    """Determine Newznab categories based on quality"""
    cats = ["5000"]  # TV
    
    quality_lower = quality.lower()
    
    if "2160" in quality_lower or "4k" in quality_lower or "uhd" in quality_lower:
        cats.extend(["5045"])  # TV/UHD
    elif "1080" in quality_lower or "720" in quality_lower or "hd" in quality_lower:
        cats.extend(["5040"])  # TV/HD
    else:
        cats.extend(["5030"])  # TV/SD
    
    # Add Foreign for German content
    cats.append("5020")  # TV/Foreign
    
    return cats


def _newznab_rss(tvdb_id_str: str, results: List, requested_cats: List[str] = None) -> XMLResponse:
    """Generate Newznab RSS feed"""
    if requested_cats is None:
        requested_cats = []
    
    rss = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:newznab="http://www.newznab.com/DTD/2007/newznab.dtd">
  <channel>
    <title>PBArr - Public Broadcasting Archive Indexer</title>
    <description>Newznab API for German Public Broadcasters</description>
    <link>http://pbarr.local/api</link>
    <language>de-de</language>
    <webMaster>pbarr@localhost</webMaster>
    <category>TV</category>
    <newznab:response offset="0" total="{len(results)}"/>
'''

    for result in results:
        # Get data from MediathekCache object
        dl_link = result.media_url or ""
        title = result.episode_title or "Unknown"
        quality = result.quality or "720p"
        season = result.season or 1
        episode = result.episode or 1
        description = result.mediathek_title or ""
        
        # Format pubDate - use created_at or current time
        pub_date = ""
        if hasattr(result, 'created_at') and result.created_at:
            try:
                pub_date = result.created_at.strftime("%a, %d %b %Y %H:%M:%S +0000")
            except:
                pub_date = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
        else:
            pub_date = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
        
        # Build item
        rss += f'''    <item>
      <title>{title}</title>
      <guid isPermaLink="false">pbarr-{tvdb_id_str}-s{season:02d}e{episode:02d}</guid>
      <link>{dl_link}</link>
      <pubDate>{pub_date}</pubDate>
      <description>{description}</description>
'''
        
        # Add categories as newznab:attr - Sonarr erwartet dieses Format
        if not requested_cats or "5000" in requested_cats:
            rss += '      <newznab:attr name="category" value="5000"/>\n'
        
        if "1080" in quality.lower() or "720" in quality.lower() or "hd" in quality.lower():
            if not requested_cats or "5040" in requested_cats:
                rss += '      <newznab:attr name="category" value="5040"/>\n'  # HD
        elif "2160" in quality.lower() or "4k" in quality.lower() or "uhd" in quality.lower():
            if not requested_cats or "5045" in requested_cats:
                rss += '      <newznab:attr name="category" value="5045"/>\n'  # UHD
        else:
            if not requested_cats or "5030" in requested_cats:
                rss += '      <newznab:attr name="category" value="5030"/>\n'  # SD
        
        if not requested_cats or "5020" in requested_cats:
            rss += '      <newznab:attr name="category" value="5020"/>\n'  # Foreign
        
        # Add newznab:attr elements
        rss += f'''      <newznab:attr name="tvdbid" value="{tvdb_id_str}"/>
      <newznab:attr name="season" value="{season}"/>
      <newznab:attr name="episode" value="{episode}"/>
      <newznab:attr name="size" value="0"/>
      <enclosure url="{dl_link}" length="0" type="application/x-nzb"/>
    </item>
'''
    
    rss += '''  </channel>
</rss>'''
    return XMLResponse(content=rss)


def _newznab_caps() -> XMLResponse:
    """Newznab capabilities endpoint - required by Sonarr"""
    caps = '''<?xml version="1.0" encoding="UTF-8"?>
<caps>
  <server version="1.0" title="PBArr" strapline="Public Broadcasting Archive Indexer" email="pbarr@localhost" url="http://pbarr.local" image="http://pbarr.local/logo.png"/>
  <limits max="100" default="100"/>
  <registration available="no" open="no"/>
  <searching>
    <search available="yes" supportedParams="q"/>
    <tv-search available="yes" supportedParams="q,tvdbid,season,ep"/>
    <movie-search available="no"/>
    <audio-search available="no"/>
    <book-search available="no"/>
  </searching>
  <categories>
    <category id="5000" name="TV">
      <subcat id="5020" name="TV/Foreign"/>
      <subcat id="5030" name="TV/SD"/>
      <subcat id="5040" name="TV/HD"/>
      <subcat id="5045" name="TV/UHD"/>
    </category>
  </categories>
  <groups/>
  <genres/>
</caps>'''
    return XMLResponse(content=caps)
