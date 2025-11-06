# PBArr Application
__version__ = "0.0.0"

try:
    from app._version import version as __version__
except ImportError:
    # Fallback for development
    __version__ = "0.0.0-dev"

# Parse version tuple safely (handle dev versions)
def parse_version_tuple(version_str):
    try:
        # Split by dots and take first 3 parts, convert to int if possible
        parts = version_str.split('.')[:3]
        return tuple(int(part) if part.isdigit() else 0 for part in parts)
    except (ValueError, AttributeError):
        return (0, 0, 0)

__version_tuple__ = parse_version_tuple(__version__)
