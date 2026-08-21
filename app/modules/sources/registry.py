"""
Finds source modules.

Every file in this package that defines a MediathekSource subclass is picked up
automatically. Adding a broadcaster means adding a file - no registration list
to edit, no import to add somewhere else. That was the point of the module idea
and it is what makes a connector for another country a self-contained addition.
"""

import importlib
import inspect
import logging
import pkgutil
from typing import Dict, List

from app.modules.sources.base import MediathekSource

logger = logging.getLogger(__name__)

_cache: Dict[str, MediathekSource] = {}


def discover_sources(refresh: bool = False) -> Dict[str, MediathekSource]:
    """
    Instantiate every source module in this package, keyed by its name.

    A module that fails to import is logged and skipped - one broken connector
    must not take the others down with it.
    """
    global _cache
    if _cache and not refresh:
        return _cache

    found: Dict[str, MediathekSource] = {}
    package = importlib.import_module("app.modules.sources")

    for info in pkgutil.iter_modules(package.__path__):
        if info.name in ("base", "registry") or info.name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"app.modules.sources.{info.name}")
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if (issubclass(obj, MediathekSource)
                        and obj is not MediathekSource
                        and not inspect.isabstract(obj)):
                    instance = obj()
                    found[instance.name] = instance
                    logger.info(f"✓ Quelle geladen: {instance.name} ({instance.country})")
        except Exception as e:
            logger.error(f"✗ Quelle '{info.name}' konnte nicht geladen werden: {e}")

    _cache = found
    return found


def enabled_sources(db=None) -> List[MediathekSource]:
    """
    The sources that should actually be queried.

    Without a session every discovered source is used. With one, the
    module_states table decides - a source unknown to the table counts as
    enabled, so a newly added connector works before anyone touches settings.
    """
    sources = discover_sources()
    if db is None:
        return list(sources.values())

    try:
        from app.models.module_state import ModuleState
        states = {
            s.module_name: s.enabled
            for s in db.query(ModuleState).filter(ModuleState.module_type == "source").all()
        }
    except Exception as e:
        logger.debug(f"Modul-Zustaende nicht lesbar ({e}) - alle Quellen aktiv")
        return list(sources.values())

    return [s for name, s in sources.items() if states.get(name, True)]
