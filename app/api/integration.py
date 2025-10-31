from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import logging
import tempfile
from datetime import datetime


from app.database import get_db
from app.models.download import Download
from app.models.mediathek_cache import MediathekCache
from app.models.tvdb_cache import TVDBCache


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/integration", tags=["integration"])


@router.get("/getnzb")
async def get_nzb(
    id: str = Query(...),
    db: Session = Depends(get_db)
):
    """
    Sonarr Download-Endpoint (On-Demand via Cache)
    
    Format: /getnzb?id=tvdb_298954_s11e01
    
    Flow:
    1. Parse TVDB ID + Season/Episode
    2. Check Cache (schnell!)
    3. If found: Create Download, Return NZB
    4. If not: 404
    """
    
    try:
        # Parse ID Format: tvdb_298954_s11e01
        parts = id.split('_')
        if len(parts) < 3 or parts[0] != 'tvdb':
            raise HTTPException(status_code=400, detail="Invalid ID format. Use: tvdb_XXXXX_sXeYY")
        
        tvdb_id = str(parts[1])
        episode_part = parts[2].lower()
        
        # Parse SeasonEpisode (z.B. s11e01)
        if not episode_part.startswith('s'):
            raise HTTPException(status_code=400, detail="Invalid format. Expected sXeYY")
        
        se_parts = episode_part.split('e')
        season = int(se_parts[0][1:])
        episode_num = int(se_parts[1])
        
        logger.info(f"Download Request: TVDB {tvdb_id} S{season:02d}E{episode_num:02d}")
        
        # Step 1: Check Cache
        cache = db.query(MediathekCache).filter(
            MediathekCache.tvdb_id == tvdb_id,
            MediathekCache.season == season,
            MediathekCache.episode == episode_num,
            MediathekCache.expires_at > datetime.utcnow()
        ).first()
        
        if not cache:
            logger.warning(f"No cache found for S{season:02d}E{episode_num:02d}")
            raise HTTPException(status_code=404, detail="Episode not found in cache")
        
        logger.info(f"✓ Cache hit: {cache.episode_title}")
        
        # Step 2: Get Show Name
        tvdb_cache = db.query(TVDBCache).filter_by(tvdb_id=tvdb_id).first()
        show_name = tvdb_cache.show_name if tvdb_cache else f"Show_{tvdb_id}"
        
        # Step 3: Create Download Entry
        filename = f"{show_name}_S{season:02d}E{episode_num:02d}.mkv"
        
        download = Download(
            tvdb_id=tvdb_id,
            season=season,
            episode_number=episode_num,
            filename=filename,
            source_url=cache.media_url,
            status="queued",
            quality=cache.quality or "720p"
        )
        db.add(download)
        db.commit()
        db.refresh(download)
        
        logger.info(f"✓ Download created: ID={download.id}, {filename}")
        
        # Step 4: Create NZB Manifest
        nzb_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE nzb PUBLIC "-//newzbin//DTD NZB 1.1//EN" "http://www.newzbin.com/DTD/nzb/nzb-1.1.dtd">
<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">
  <head>
    <meta type="title">PBArr - {show_name} S{season:02d}E{episode_num:02d}</meta>
    <meta type="description">On-Demand Download via PBArr</meta>
  </head>
  <file poster="pbarr@pbarr.local" date="{int(datetime.utcnow().timestamp())}" subject="{filename}">
    <groups>
      <group>pbarr</group>
    </groups>
    <segments>
      <segment bytes="0" number="1">pbarr-download-{download.id}</segment>
    </segments>
  </file>
</nzb>'''
        
        # Save temporarily
        with tempfile.NamedTemporaryFile(mode='w', suffix='.nzb', delete=False) as f:
            f.write(nzb_content)
            nzb_path = f.name
        
        logger.info(f"NZB created: {nzb_path}")
        
        # Return NZB
        return FileResponse(
            path=nzb_path,
            filename=filename.replace('.mkv', '.nzb'),
            media_type="application/x-nzb"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"NZB Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download-status")
async def download_status(download_id: int = Query(...), db: Session = Depends(get_db)):
    """Sonarr fragt Download-Status ab"""
    download = db.query(Download).filter_by(id=download_id).first()
    
    if not download:
        return {"status": "unknown"}
    
    return {
        "status": download.status,
        "filename": download.filename,
        "progress": download.progress or 0,
        "created_at": download.created_at,
        "completed_at": download.completed_at
    }
