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
    def __init__(self, season: int, episode: int, confidence: float, match_type: str, episode_title: str = None):
        self.season = season
        self.episode = episode
        self.confidence = confidence
        self.match_type = match_type
        self.episode_title = episode_title

class EpisodeMatcher:
    """Matches MediathekViewWeb Episodes with TVDB"""

    def __init__(self, db: Session):
        self.db = db

    def filter_excluded_keywords(self, mediathek_episode: dict, exclude_keywords_string: str) -> bool:
        """
        Filtert Episoden basierend auf exclude_keywords.
        Gibt False zurück wenn die Episode ausgeschlossen werden soll.

        Args:
            mediathek_episode: Episode dict mit 'title' und 'description'
            exclude_keywords_string: Komma-separierte Keywords, z.B. "klare Sprache, Audiodeskription, Gebärdensprache"

        Returns:
            True wenn Episode behalten werden soll, False wenn ausgeschlossen
        """
        if not exclude_keywords_string or not exclude_keywords_string.strip():
            return True  # Keine Filter = Episode behalten

        # Split nach "," (ohne Space nach Komma) und strip whitespace
        keywords = [kw.strip() for kw in exclude_keywords_string.split(",") if kw.strip()]

        if not keywords:
            return True

        episode_title = mediathek_episode.get('title', '').lower()

        # Prüfe jedes Keyword case-insensitive NUR im Titel (nicht in Beschreibung)
        for keyword in keywords:
            keyword_lower = keyword.lower()
            if keyword_lower in episode_title:
                logger.debug(f"Episode excluded due to keyword '{keyword}': {mediathek_episode.get('title', '')}")
                return False  # Episode ausschließen

        return True  # Episode behalten
    
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
        tvdb_episodes: List[dict],
        exclude_keywords_string: str = ""
    ) -> Optional[MatchResult]:
        """
        Matched eine MediathekViewWeb Episode mit TVDB Episodes

        Strategy:
        1. Filter excluded keywords (am ANFANG!)
        2. Exaktes Datum-Match
        3. Gäste-Namen Match
        4. Datum-Nähe (±14 Tage) + Content
        5. Datum-Nähe (±7 Tage) fallback
        """

        # DEBUG: Log available TVDB episodes
        logger.debug(f"Total TVDB episodes available: {len(tvdb_episodes)}")
        if tvdb_episodes:
            seasons = set(ep.get('season', 0) for ep in tvdb_episodes)
            logger.debug(f"TVDB seasons: {sorted(seasons)}")
            # Show sample episodes
            for i, ep in enumerate(tvdb_episodes[:3]):
                logger.debug(f"  TVDB Sample {i+1}: S{ep.get('season', '?')}E{ep.get('episode', '?')} - {ep.get('name', 'Unknown')}")

        # Step 1: Filter excluded keywords AM ANFANG!
        if not self.filter_excluded_keywords(mediathek_episode, exclude_keywords_string):
            logger.info(f"🚫 Episode filtered out due to excluded keywords: {mediathek_episode.get('title', '')}")
            return None

        mediathek_title = mediathek_episode.get('title', '')
        mediathek_pub = mediathek_episode.get('pub_date', '')
        mediathek_desc = mediathek_episode.get('description', '')

        mediathek_date = self.extract_date(mediathek_pub)
        mediathek_guests = self.extract_guests(mediathek_title)

        logger.debug(f"Matching: {mediathek_title}")
        logger.debug(f"  Date: {mediathek_date}")
        logger.debug(f"  Guests: {mediathek_guests}")
        logger.debug(f"Matching against {len(tvdb_episodes)} TVDB episodes")
        
        # Strategy 0: TITEL-MATCHING (höchste Priorität!)
        logger.debug(f"  Trying title match...")
        for tvdb_ep in tvdb_episodes:
            tvdb_title = tvdb_ep.get('name', '').strip()
            if not tvdb_title:
                continue

            # Normalisiere beide Titel für besseren Vergleich
            mediathek_title_clean = self._normalize_title_for_matching(mediathek_title)
            tvdb_title_clean = self._normalize_title_for_matching(tvdb_title)

            # Exakter Titel-Match (case-insensitive)
            if mediathek_title_clean.lower() == tvdb_title_clean.lower():
                logger.info(f"✓ EXACT TITLE MATCH: '{mediathek_title}' → S{tvdb_ep['season']:02d}E{tvdb_ep['episode']:02d} ('{tvdb_title}')")
                return MatchResult(
                    season=tvdb_ep['season'],
                    episode=tvdb_ep['episode'],
                    confidence=0.95,
                    match_type="exactTitle",
                    episode_title=tvdb_title
                )

            # Fuzzy Titel-Match (Episode-Nummern in Klammern ignorieren)
            # Beispiel: "Doppelleben" sollte mit "Doppelleben (258)" matchen
            mediathek_no_numbers = re.sub(r'\s*\(\d+\)\s*$', '', mediathek_title_clean)
            tvdb_no_numbers = re.sub(r'\s*\(\d+\)\s*$', '', tvdb_title_clean)

            if mediathek_no_numbers.lower() == tvdb_no_numbers.lower():
                logger.info(f"✓ FUZZY TITLE MATCH: '{mediathek_title}' → S{tvdb_ep['season']:02d}E{tvdb_ep['episode']:02d} ('{tvdb_title}')")
                return MatchResult(
                    season=tvdb_ep['season'],
                    episode=tvdb_ep['episode'],
                    confidence=0.90,
                    match_type="fuzzyTitle",
                    episode_title=tvdb_title
                )

            # Teilstring-Match (wenn einer im anderen enthalten ist)
            if (mediathek_no_numbers.lower() in tvdb_no_numbers.lower() or
                tvdb_no_numbers.lower() in mediathek_no_numbers.lower()):
                if len(mediathek_no_numbers) > 5 and len(tvdb_no_numbers) > 5:  # Vermeide zu kurze Matches
                    logger.info(f"✓ SUBSTRING TITLE MATCH: '{mediathek_title}' → S{tvdb_ep['season']:02d}E{tvdb_ep['episode']:02d} ('{tvdb_title}')")
                    return MatchResult(
                        season=tvdb_ep['season'],
                        episode=tvdb_ep['episode'],
                        confidence=0.85,
                        match_type="substringTitle",
                        episode_title=tvdb_title
                    )

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
                        logger.info(f"✓ EXACT DATE MATCH: S{tvdb_ep['season']:02d}E{tvdb_ep['episode']:02d}")
                        result = MatchResult(
                            season=tvdb_ep['season'],
                            episode=tvdb_ep['episode'],
                            confidence=1.0,
                            match_type="exactDate",
                            episode_title=tvdb_ep.get('name', '')
                        )
                        logger.info(f"Created MatchResult: S{result.season:02d}E{result.episode:02d}")
                        return result
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
                    logger.info(f"✓ GUEST MATCH: S{tvdb_ep['season']:02d}E{tvdb_ep['episode']:02d} - {tvdb_name}")
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
                            logger.info(f"✓ CONTENT MATCH: S{tvdb_ep['season']:02d}E{tvdb_ep['episode']:02d} ({days_diff} days, {names_found} names)")
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
                        logger.info(f"✓ NEAR DATE MATCH: S{tvdb_ep['season']:02d}E{tvdb_ep['episode']:02d} ({days_diff} days)")
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

    def _normalize_title_for_matching(self, title: str) -> str:
        """
        Normalisiert Titel für besseres Matching:
        - Umlaute konvertieren (ä→ae, ö→oe, ü→ue, ß→ss)
        - Sonderzeichen entfernen
        - Mehrfach-Spaces zu Single-Space
        - Case-insensitive Vergleich
        """
        if not title:
            return ""

        # Umlaute konvertieren
        title = title.replace('ä', 'ae').replace('Ä', 'Ae')
        title = title.replace('ö', 'oe').replace('Ö', 'Oe')
        title = title.replace('ü', 'ue').replace('Ü', 'Ue')
        title = title.replace('ß', 'ss')

        # Sonderzeichen entfernen, aber Klammern und Zahlen behalten für Episode-Nummern
        title = re.sub(r'[^\w\s\(\)\d]', '', title)

        # Mehrfach-Spaces entfernen
        title = re.sub(r'\s+', ' ', title)

        return title.strip()
