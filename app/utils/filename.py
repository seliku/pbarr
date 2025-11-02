import re

def normalize_filename(text: str) -> str:
    """Remove problematic filesystem chars, keep diacritics/umlauts"""
    if not text:
        return ""

    # Only remove these problematic characters for filesystems
    # Keep: letters, numbers, spaces, and diacritics (ü, é, ñ, etc)
    normalized = re.sub(r'[?!*<>:/\\\\|&\\-]', '', text)
    # Clean up multiple spaces
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return normalized
