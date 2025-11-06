# PBArr Application
__version__ = "0.0.0"

try:
    from app._version import version as __version__
except ImportError:
    # Fallback for development
    __version__ = "0.0.0-dev"

__version_tuple__ = tuple(map(int, __version__.split('.')[:3]))
