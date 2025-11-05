"""
Network utilities for PBArr - simplified HTTP client functions
"""
import httpx
from typing import Optional, Dict, Any
import aiohttp
import logging

logger = logging.getLogger(__name__)


def create_aiohttp_session(**kwargs) -> aiohttp.ClientSession:
    """
    Create an aiohttp ClientSession.

    Args:
        **kwargs: Additional arguments for ClientSession

    Returns:
        Configured aiohttp.ClientSession
    """
    return aiohttp.ClientSession(**kwargs)


def create_httpx_client(**kwargs) -> httpx.AsyncClient:
    """
    Create an httpx AsyncClient.

    Args:
        **kwargs: Additional arguments for AsyncClient

    Returns:
        Configured httpx.AsyncClient
    """
    return httpx.AsyncClient(**kwargs)


def create_httpx_sync_client(**kwargs) -> httpx.Client:
    """
    Create an httpx synchronous Client.

    Args:
        **kwargs: Additional arguments for Client

    Returns:
        Configured httpx.Client
    """
    return httpx.Client(**kwargs)


def get_proxy_for_url(url: str) -> Optional[str]:
    """
    Get proxy URL for a given URL. Currently returns None (no proxy).

    Args:
        url: The URL to get proxy for

    Returns:
        Proxy URL or None if no proxy should be used
    """
    # TODO: Implement proxy configuration lookup from database
    return None
