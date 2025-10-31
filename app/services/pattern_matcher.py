"""
Flexible Pattern Matcher - User-definierbar
Unterstützt Regex, Named Groups, Custom Logic
"""
import logging
import re
from typing import Optional, Dict, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class MatchResult:
    """Ergebnis eines Pattern Matches"""
    title: Optional[str]
    season: int
    episode: int
    success: bool
    reason: str = ""

class PatternMatcher:
    """Intelligent Pattern Matching mit Regex"""
    
    def __init__(self, config: 'MatcherConfig' = None):
        self.config = config
        self.title_pattern = None
        self.season_pattern = None
        self.episode_pattern = None
        
        if config:
            self._compile_patterns()
    
    def _compile_patterns(self):
        """Kompiliert Regex Patterns"""
        try:
            if self.config.title_pattern:
                self.title_pattern = re.compile(self.config.title_pattern, re.IGNORECASE)
            if self.config.season_pattern:
                self.season_pattern = re.compile(self.config.season_pattern, re.IGNORECASE)
            if self.config.episode_pattern:
                self.episode_pattern = re.compile(self.config.episode_pattern, re.IGNORECASE)
        except re.error as e:
            logger.error(f"Pattern compilation error: {e}")
            raise
    
    def match(self, text: str) -> MatchResult:
        """
        Extrahiert Title, Season, Episode aus Text
        """
        if not self.config:
            return MatchResult(title=None, season=1, episode=0, success=False, reason="No config")
        
        try:
            title = None
            season = self.config.default_season
            episode = None
            
            # Title extrahieren
            if self.title_pattern:
                title_match = self.title_pattern.search(text)
                if title_match:
                    try:
                        title = title_match.group(self.config.title_group)
                        logger.debug(f"Extracted title: {title}")
                    except IndexError:
                        logger.warning(f"Title group {self.config.title_group} not found")
            
            # Season extrahieren
            if self.season_pattern:
                season_match = self.season_pattern.search(text)
                if season_match:
                    try:
                        season_str = season_match.group(self.config.season_group)
                        season = int(season_str)
                        logger.debug(f"Extracted season: {season}")
                    except (IndexError, ValueError):
                        logger.debug(f"Season extraction failed, using default: {season}")
            
            # Episode extrahieren
            if self.episode_pattern:
                ep_match = self.episode_pattern.search(text)
                if ep_match:
                    try:
                        ep_str = ep_match.group(self.config.episode_group)
                        episode = int(ep_str)
                        logger.debug(f"Extracted episode: {episode}")
                    except (IndexError, ValueError) as e:
                        logger.warning(f"Episode extraction failed: {e}")
            
            if episode is None:
                return MatchResult(
                    title=title,
                    season=season,
                    episode=0,
                    success=False,
                    reason="Could not extract episode number"
                )
            
            return MatchResult(
                title=title or "Unknown",
                season=season,
                episode=episode,
                success=True,
                reason="Matched successfully"
            )
        
        except Exception as e:
            logger.error(f"Pattern matching error: {e}")
            return MatchResult(
                title=None,
                season=1,
                episode=0,
                success=False,
                reason=str(e)
            )
    
    def test(self, test_string: str) -> Dict:
        """Test Matcher gegen Test-String"""
        result = self.match(test_string)
        return {
            "success": result.success,
            "title": result.title,
            "season": result.season,
            "episode": result.episode,
            "reason": result.reason
        }

class MatcherTemplates:
    """Vordefinierte Matcher für verschiedene Mediatheken"""
    
    # ARD: "Die Sendung mit der Maus - Folge 42"
    ARD_SIMPLE = {
        "strategy": "regex",
        "title_pattern": r"^(.+?)\s*-\s*Folge",
        "season_pattern": None,  # Optional
        "episode_pattern": r"Folge\s*(\d+)",
        "title_group": 1,
        "season_group": 1,
        "episode_group": 1,
        "default_season": 1,
    }
    
    # ZDF: "Das Duell S2E3 - Der Titel"
    ZDF_STANDARD = {
        "strategy": "regex",
        "title_pattern": r"^(.+?)\s+S\d+E\d+",
        "season_pattern": r"S(\d+)",
        "episode_pattern": r"E(\d+)",
        "title_group": 1,
        "season_group": 1,
        "episode_group": 1,
        "default_season": 1,
    }
    
    # Generic: "Show Title S01E05"
    GENERIC_STANDARD = {
        "strategy": "regex",
        "title_pattern": r"^(.+?)\s+S\d+E\d+",
        "season_pattern": r"S(\d+)",
        "episode_pattern": r"E(\d+)",
        "title_group": 1,
        "season_group": 1,
        "episode_group": 1,
        "default_season": 1,
    }
