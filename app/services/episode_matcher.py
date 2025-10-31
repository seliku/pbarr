"""
Episode Matcher - Intelligent matching for German TV Shows
Matches based on: Exact Date, Guest Names, Content, Date Proximity
"""
import logging
from typing import Optional, Tuple, List
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import re

logger = logging.getLogger(__name__)

class MatchResult:
    def __init__(self, season: int, episode: int, confidence: float, match_type: str):
        self.season = season
        self.episode = episode
        self.confidence = confidence
        self.match_type = match_type

class EpisodeMatcher:
    """Matches MediathekViewWeb Episodes with TVDB"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def extract_guests(self, title: str) -> List[str]:
        """Extrahiert Gäste-Namen aus Titel"""
        # Pattern: "Show mit Guest1 & Guest2"
        match = re.search(r'mit\s+(.+?)(?:\s*-|\s*$)', title, re.IGNORECASE)
        if not match:
            return []
        
        guests_str = match.group(1)
        
        # Entferne "und", "&", Sonderzeichen
        guests_str = re.sub(r'\s+(und|&)\s+', ' ', guests_str, flags=re.IGNORECASE)
        guests_str = re.sub(r'[^\w\s]', '', guests_str)
        
        # Split zu einzelnen Namen (>2 chars)
        guests = [g.strip() for g in guests_str.split() if len(g.strip()) > 2]
        return guests
    
    def extract_date(self, date_str: str) -> Optional[datetime]:
        """Konvertiert Date String zu datetime"""
        if not date_str:
            return None
        
        try:
            # Format: "Mon, 15 Mar 2027 23:15:00 GMT"
            return datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %Z")
        except:
            try:
                # Fallback
                return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            except:
                return None
    
    def date_distance(self, date1: datetime, date2: datetime) -> int:
        """Abstand zwischen zwei Daten in Tagen"""
        if not date1 or not date2:
            return 999
        return abs((date1 - date2).days)
    
    def match_episode(
        self,
        mediathek_episode: dict,
        tvdb_episodes: List[dict]
    ) -> Optional[MatchResult]:
        """
        Matched eine MediathekViewWeb Episode mit TVDB Episodes
        
        Strategy:
        1. Exaktes Datum-Match
        2. Gäste-Namen Match
        3. Datum-Nähe (±14 Tage) + Content
        4. Datum-Nähe (±7 Tage) fallback
        """
        
        mediathek_title = mediathek_episode.get('title', '')
        mediathek_pub = mediathek_episode.get('pub_date', '')
        mediathek_desc = mediathek_episode.get('description', '')
        
        mediathek_date = self.extract_date(mediathek_pub)
        mediathek_guests = self.extract_guests(mediathek_title)
        
        logger.debug(f"Matching: {mediathek_title}")
        logger.debug(f"  Date: {mediathek_date}")
        logger.debug(f"  Guests: {mediathek_guests}")
        
        # Strategy 1: Exaktes Datum-Match
        if mediathek_date:
            for tvdb_ep in tvdb_episodes:
                tvdb_aired = tvdb_ep.get('aired')
                if not tvdb_aired:
                    continue
                
                try:
                    tvdb_date = datetime.fromisoformat(tvdb_aired)
                    
                    # Vergleiche nur das Datum (nicht Zeit)
                    if mediathek_date.date() == tvdb_date.date():
                        logger.info(f"✓ EXACT DATE MATCH: S{tvdb_ep['season']}E{tvdb_ep['episode']}")
                        return MatchResult(
                            season=tvdb_ep['season'],
                            episode=tvdb_ep['episode'],
                            confidence=1.0,
                            match_type="exactDate"
                        )
                except:
                    pass
        
        # Strategy 2: Gäste-Namen Match
        if mediathek_guests and len(mediathek_guests) > 0:
            logger.debug(f"  Trying guest match with: {mediathek_guests}")
            
            for tvdb_ep in tvdb_episodes:
                tvdb_name = tvdb_ep.get('name', '')
                
                # Bereinige TVDB Name
                tvdb_clean = re.sub(r'[&]', ' ', tvdb_name)
                tvdb_clean = re.sub(r'[^\w\s]', '', tvdb_clean).lower()
                
                # Prüfe ob ALLE Gäste im TVDB Name vorhanden
                all_guests_found = all(guest.lower() in tvdb_clean for guest in mediathek_guests)
                
                if all_guests_found:
                    logger.info(f"✓ GUEST MATCH: S{tvdb_ep['season']}E{tvdb_ep['episode']} - {tvdb_name}")
                    return MatchResult(
                        season=tvdb_ep['season'],
                        episode=tvdb_ep['episode'],
                        confidence=0.95,
                        match_type="guestName"
                    )
        
        # Strategy 3: Content + Date Proximity (±14 Tage)
        if mediathek_date and mediathek_desc:
            logger.debug(f"  Trying content match (±14 days)...")
            
            for tvdb_ep in tvdb_episodes:
                tvdb_aired = tvdb_ep.get('aired')
                if not tvdb_aired:
                    continue
                
                try:
                    tvdb_date = datetime.fromisoformat(tvdb_aired)
                    days_diff = self.date_distance(mediathek_date, tvdb_date)
                    
                    if days_diff <= 14:
                        tvdb_name = tvdb_ep.get('name', '')
                        
                        # Extrahiere Namen aus TVDB (>3 chars)
                        tvdb_names = re.split(r'[&\s]+', tvdb_name)
                        tvdb_names = [n for n in tvdb_names if len(n) > 3]
                        
                        # Prüfe ob Namen in Content vorkommen
                        mediathek_desc_lower = mediathek_desc.lower()
                        names_found = sum(1 for name in tvdb_names if name.lower() in mediathek_desc_lower)
                        
                        if names_found > 0:
                            confidence = 0.8 - (days_diff * 0.01)
                            logger.info(f"✓ CONTENT MATCH: S{tvdb_ep['season']}E{tvdb_ep['episode']} ({days_diff} days, {names_found} names)")
                            return MatchResult(
                                season=tvdb_ep['season'],
                                episode=tvdb_ep['episode'],
                                confidence=confidence,
                                match_type="contentName"
                            )
                except:
                    pass
        
        # Strategy 4: Datum-Nähe fallback (±7 Tage)
        if mediathek_date:
            logger.debug(f"  Trying date proximity (±7 days)...")
            
            for tvdb_ep in tvdb_episodes:
                tvdb_aired = tvdb_ep.get('aired')
                if not tvdb_aired:
                    continue
                
                try:
                    tvdb_date = datetime.fromisoformat(tvdb_aired)
                    days_diff = self.date_distance(mediathek_date, tvdb_date)
                    
                    if days_diff <= 7:
                        confidence = 0.65 - (days_diff * 0.05)
                        logger.info(f"✓ NEAR DATE MATCH: S{tvdb_ep['season']}E{tvdb_ep['episode']} ({days_diff} days)")
                        return MatchResult(
                            season=tvdb_ep['season'],
                            episode=tvdb_ep['episode'],
                            confidence=confidence,
                            match_type="nearDate"
                        )
                except:
                    pass
        
        logger.debug(f"✗ No match found")
        return None
