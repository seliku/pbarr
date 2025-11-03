"""
Network utilities for PBArr with smart SOCKS5 proxy routing
"""
import asyncio
import httpx
from typing import Optional, Dict, Any
import aiohttp
import logging
from urllib.parse import urlparse
import os
import ipaddress
import time
import re
import socket
from concurrent.futures import ThreadPoolExecutor
import atexit

logger = logging.getLogger(__name__)

# Cache for proxy settings (TTL: 5 minutes)
_PROXY_CACHE = {
    'value': None,
    'timestamp': 0,
    'ttl': 300  # 5 minutes
}

# Thread pool for DNS resolution (non-blocking)
_dns_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dns")


def _cleanup_dns_executor():
    """Clean up DNS executor on application shutdown."""
    logger.debug("Shutting down DNS executor")
    _dns_executor.shutdown(wait=True)


# Register cleanup on application exit
atexit.register(_cleanup_dns_executor)


def parse_socks5_proxy(proxy_input: str) -> Optional[Dict[str, Any]]:
    """
    Parse and validate SOCKS5 proxy URL.

    Supports multiple formats:
    - socks5://host:port
    - socks5://user:pass@host:port
    - host:port
    - host:port:user:pass

    Args:
        proxy_input: Proxy configuration string

    Returns:
        Dict with parsed proxy info or None if invalid
    """
    if not proxy_input or not proxy_input.strip():
        return None

    proxy_input = proxy_input.strip()

    # Auto-prefix socks5:// if missing
    if not proxy_input.startswith(('socks5://', 'http://', 'https://')):
        if '@' in proxy_input:
            # Format: host:port:user:pass
            parts = proxy_input.split(':')
            if len(parts) == 4:
                host, port, user, password = parts
                proxy_input = f"socks5://{user}:{password}@{host}:{port}"
            else:
                logger.warning(f"Invalid proxy format (expected host:port:user:pass): {proxy_input}")
                return None
        else:
            # Format: host:port
            parts = proxy_input.split(':')
            if len(parts) == 2:
                host, port = parts
                proxy_input = f"socks5://{host}:{port}"
            else:
                logger.warning(f"Invalid proxy format (expected host:port): {proxy_input}")
                return None

    try:
        parsed = urlparse(proxy_input)

        if parsed.scheme not in ('socks5', 'http', 'https'):
            logger.warning(f"Unsupported proxy scheme: {parsed.scheme}")
            return None

        # Validate host
        if not parsed.hostname:
            logger.warning(f"Invalid proxy host: {proxy_input}")
            return None

        # Validate port
        port = parsed.port
        if port is None:
            port = 1080  # Default SOCKS5 port
        elif not (1 <= port <= 65535):
            logger.warning(f"Invalid proxy port: {port}")
            return None

        result = {
            'host': parsed.hostname,
            'port': port,
            'username': parsed.username,
            'password': parsed.password,
            'url': proxy_input
        }

        logger.debug(f"Parsed SOCKS5 proxy: {parsed.hostname}:{port}")
        return result

    except Exception as e:
        logger.warning(f"Error parsing proxy URL '{proxy_input}': {e}")
        return None


async def resolve_hostname_async(hostname: str, timeout: float = 5.0) -> Optional[str]:
    """
    Non-blocking DNS resolution using thread pool with timeout.

    Args:
        hostname: Hostname to resolve
        timeout: DNS resolution timeout in seconds (default: 5.0)

    Returns:
        IP address string or None if resolution fails or times out
    """
    try:
        loop = asyncio.get_event_loop()
        ip = await asyncio.wait_for(
            loop.run_in_executor(_dns_executor, socket.gethostbyname, hostname),
            timeout=timeout
        )
        return ip
    except asyncio.TimeoutError:
        logger.warning(f"DNS resolution timeout for {hostname}")
        return None
    except socket.gaierror:
        return None


async def should_use_proxy_async(url: str) -> bool:
    """
    Async version of should_use_proxy with non-blocking DNS resolution.

    Returns False for:
    - Loopback IPs (127.0.0.1, ::1)
    - Private IPs (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
    - Link-local IPs (169.254.0.0/16)
    - Local hostnames (localhost, sonarr, radarr, *.local, *.internal)

    Returns True for all external IPs/domains.

    Args:
        url: URL to check

    Returns:
        True if proxy should be used, False otherwise
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname

        if not hostname:
            logger.debug(f"No hostname in URL: {url}")
            return False

        # Quick local hostname checks (no DNS needed)
        localhost_names = {'localhost', 'broadcasthost', 'sonarr', 'radarr'}
        if hostname.lower() in localhost_names:
            logger.debug(f"Skipping proxy for localhost hostname: {url}")
            return False

        # Check for internal domain suffixes
        internal_suffixes = ('.local', '.internal', '.lan', '.home')
        if any(hostname.lower().endswith(suffix) for suffix in internal_suffixes):
            logger.debug(f"Skipping proxy for internal domain: {url}")
            return False

        # DNS resolution (async, non-blocking)
        ip_addr = await resolve_hostname_async(hostname)
        if not ip_addr:
            # DNS resolution failed - assume external
            logger.debug(f"DNS resolution failed for {hostname}, assuming external: {url}")
            return True

        # Check if IP is private/internal
        try:
            ip_obj = ipaddress.ip_address(ip_addr)

            # Loopback addresses
            if ip_obj.is_loopback:
                logger.debug(f"Skipping proxy for loopback IP {ip_addr}: {url}")
                return False

            # Private networks
            private_networks = [
                ipaddress.ip_network('10.0.0.0/8'),
                ipaddress.ip_network('172.16.0.0/12'),
                ipaddress.ip_network('192.168.0.0/16'),
                ipaddress.ip_network('169.254.0.0/16'),  # Link-local
            ]

            for network in private_networks:
                if ip_obj in network:
                    logger.debug(f"Skipping proxy for private IP {ip_addr}: {url}")
                    return False

        except ValueError:
            # Invalid IP format - assume external
            logger.debug(f"Invalid IP format {ip_addr}, assuming external: {url}")
            return True

        # External IP/domain
        logger.debug(f"Using proxy for external URL: {url}")
        return True

    except Exception as e:
        logger.warning(f"Error checking proxy routing for {url}: {e}")
        # On error, default to using proxy for safety
        return True


def should_use_proxy(url: str) -> bool:
    """
    Synchronous version of should_use_proxy (fast, limited DNS checks).

    Use should_use_proxy_async() in async contexts for full DNS resolution.

    Returns False for:
    - Local hostnames (localhost, sonarr, radarr, *.local, *.internal)
    - Known private IP patterns

    Returns True for everything else (assumes external).

    Args:
        url: URL to check

    Returns:
        True if proxy should be used, False otherwise
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname

        if not hostname:
            logger.debug(f"No hostname in URL: {url}")
            return False

        # Quick local hostname checks (no DNS needed)
        localhost_names = {'localhost', 'broadcasthost', 'sonarr', 'radarr'}
        if hostname.lower() in localhost_names:
            logger.debug(f"Skipping proxy for localhost hostname: {url}")
            return False

        # Check for internal domain suffixes
        internal_suffixes = ('.local', '.internal', '.lan', '.home')
        if any(hostname.lower().endswith(suffix) for suffix in internal_suffixes):
            logger.debug(f"Skipping proxy for internal domain: {url}")
            return False

        # For sync version, assume external by default (no DNS lookup)
        logger.debug(f"Assuming external URL (no DNS check): {url}")
        return True

    except Exception as e:
        logger.warning(f"Error checking proxy routing for {url}: {e}")
        return True


def get_socks5_proxy_url() -> Optional[str]:
    """
    Get the configured SOCKS5 proxy URL from database with caching.

    Cache TTL: 5 minutes
    Returns cached value if within TTL, otherwise queries DB.

    Returns:
        Proxy URL string or None if not configured
    """
    global _PROXY_CACHE
    current_time = time.time()

    # Check cache validity
    if (_PROXY_CACHE['value'] is not None and
        current_time - _PROXY_CACHE['timestamp'] < _PROXY_CACHE['ttl']):
        logger.debug("SOCKS5 proxy cache hit")
        return _PROXY_CACHE['value']

    # Cache miss or expired - query database
    try:
        from app.database import SessionLocal
        from app.models.config import Config

        db = SessionLocal()
        try:
            config = db.query(Config).filter_by(key="socks5_proxy").first()
            if config and config.value and config.value.strip():
                proxy_input = config.value.strip()
                parsed = parse_socks5_proxy(proxy_input)
                if parsed:
                    proxy_url = parsed['url']
                    _PROXY_CACHE['value'] = proxy_url
                    _PROXY_CACHE['timestamp'] = current_time
                    logger.debug(f"SOCKS5 proxy cache updated: {proxy_url}")
                    return proxy_url
                else:
                    logger.warning(f"Invalid SOCKS5 proxy format: {proxy_input}")
            else:
                logger.debug("No SOCKS5 proxy configured")

            # No valid proxy - cache None
            _PROXY_CACHE['value'] = None
            _PROXY_CACHE['timestamp'] = current_time
            return None

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error getting SOCKS5 proxy config: {e}")
        # On DB error, return cached value if available (better than breaking)
        if _PROXY_CACHE['value'] is not None:
            logger.warning("Using cached proxy value due to DB error")
            return _PROXY_CACHE['value']
        return None


def get_proxy_for_url(url: str) -> Optional[str]:
    """
    Get proxy URL for a specific URL based on smart routing.

    Normalizes proxy URL format for httpx compatibility (socks5h:// for remote DNS).

    Args:
        url: URL to check

    Returns:
        Proxy URL if should use proxy, None for direct connection
    """
    if should_use_proxy(url):
        proxy_url = get_socks5_proxy_url()
        if proxy_url:
            # Normalize for httpx: use socks5h:// for remote DNS resolution
            if proxy_url.startswith('socks5://'):
                proxy_url = proxy_url.replace('socks5://', 'socks5h://', 1)
            logger.debug(f"Using SOCKS5 proxy for {url}")
            return proxy_url
        else:
            logger.debug(f"No proxy configured for external URL: {url}")
            return None
    else:
        logger.debug(f"Direct connection for local URL: {url}")
        return None


def clear_proxy_cache():
    """Clear the proxy cache (useful when settings change)"""
    global _PROXY_CACHE
    _PROXY_CACHE['value'] = None
    _PROXY_CACHE['timestamp'] = 0
    logger.debug("SOCKS5 proxy cache cleared")


def create_aiohttp_connector(proxy_url: Optional[str] = None) -> aiohttp.TCPConnector:
    """
    Create an aiohttp TCPConnector with optional SOCKS5 proxy support.

    Args:
        proxy_url: SOCKS5 proxy URL (socks5://user:pass@host:port or socks5://host:port)

    Returns:
        Configured aiohttp.TCPConnector
    """
    if proxy_url:
        try:
            import aiohttp_socks

            parsed = parse_socks5_proxy(proxy_url)
            if not parsed:
                logger.warning(f"Invalid proxy URL: {proxy_url}")
                return aiohttp.TCPConnector()

            logger.info(f"Using SOCKS5 proxy for aiohttp: {parsed['host']}:{parsed['port']}")

            connector = aiohttp_socks.ProxyConnector(
                proxy_type=aiohttp_socks.ProxyType.SOCKS5,
                host=parsed['host'],
                port=parsed['port'],
                username=parsed['username'],
                password=parsed['password'],
                rdns=True  # Remote DNS resolution
            )
            return connector
        except ImportError:
            logger.warning("aiohttp-socks not installed, SOCKS5 proxy not available")
            return aiohttp.TCPConnector()
        except Exception as e:
            logger.error(f"Error configuring SOCKS5 proxy for aiohttp: {e}")
            return aiohttp.TCPConnector()
    else:
        return aiohttp.TCPConnector()


def create_aiohttp_session(proxy_url: Optional[str] = None, **kwargs) -> aiohttp.ClientSession:
    """
    Create an aiohttp ClientSession with optional SOCKS5 proxy support.

    Args:
        proxy_url: SOCKS5 proxy URL
        **kwargs: Additional arguments for ClientSession

    Returns:
        Configured aiohttp.ClientSession
    """
    connector = create_aiohttp_connector(proxy_url)
    return aiohttp.ClientSession(connector=connector, **kwargs)


def create_httpx_client(proxy_url: Optional[str] = None, **kwargs) -> httpx.AsyncClient:
    """
    Create an httpx AsyncClient with optional SOCKS5 proxy support.

    Args:
        proxy_url: SOCKS5 proxy URL
        **kwargs: Additional arguments for AsyncClient

    Returns:
        Configured httpx.AsyncClient
    """
    if proxy_url:
        try:
            # httpx supports SOCKS proxies via the proxies parameter
            proxies = {
                'http://': proxy_url,
                'https://': proxy_url
            }
            logger.info(f"Using SOCKS5 proxy for httpx: {proxy_url}")
            return httpx.AsyncClient(proxies=proxies, **kwargs)
        except Exception as e:
            logger.error(f"Error configuring SOCKS5 proxy for httpx: {e}")
            return httpx.AsyncClient(**kwargs)
    else:
        return httpx.AsyncClient(**kwargs)


def create_httpx_sync_client(proxy_url: Optional[str] = None, **kwargs) -> httpx.Client:
    """
    Create an httpx synchronous Client with optional SOCKS5 proxy support.

    Args:
        proxy_url: SOCKS5 proxy URL
        **kwargs: Additional arguments for Client

    Returns:
        Configured httpx.Client
    """
    if proxy_url:
        try:
            # httpx supports SOCKS proxies via the proxies parameter
            proxies = {
                'http://': proxy_url,
                'https://': proxy_url
            }
            logger.info(f"Using SOCKS5 proxy for httpx sync: {proxy_url}")
            return httpx.Client(proxies=proxies, **kwargs)
        except Exception as e:
            logger.error(f"Error configuring SOCKS5 proxy for httpx sync: {e}")
            return httpx.Client(**kwargs)
    else:
        return httpx.Client(**kwargs)


async def fetch_with_fallback(
    url: str,
    proxy_url: Optional[str] = None,
    timeout: float = 30.0,
    headers: Optional[Dict[str, str]] = None,
    **kwargs
) -> httpx.Response:
    """
    Fetch URL with proxy, fallback to direct connection on failure.

    Supports custom headers for both proxy and direct connections.
    Uses longer timeouts for proxy connections (1.5x default timeout).

    Args:
        url: URL to fetch
        proxy_url: Optional proxy URL override
        timeout: Base timeout in seconds (default: 30.0)
        headers: Custom HTTP headers
        **kwargs: Additional arguments for httpx

    Returns:
        httpx.Response object

    Raises:
        httpx.HTTPError: If both proxy and direct connection fail
    """
    # Default headers
    if headers is None:
        headers = {}

    # Add User-Agent if not present
    if 'user-agent' not in {k.lower() for k in headers.keys()}:
        headers['User-Agent'] = 'PBArr/1.0'

    # Determine proxy for this URL
    if proxy_url is None:
        proxy_url = get_proxy_for_url(url)

    # Try with proxy first (if configured)
    if proxy_url:
        try:
            # Use longer timeout for proxy connections
            proxy_timeout = timeout * 1.5
            async with create_httpx_client(
                proxy_url=proxy_url,
                timeout=proxy_timeout,
                **kwargs
            ) as client:
                logger.debug(f"Fetching via proxy: {url}")
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response
        except Exception as e:
            logger.warning(f"SOCKS5 proxy failed ({proxy_url}), falling back to direct connection: {e}")

    # Fallback to direct connection
    try:
        async with httpx.AsyncClient(timeout=timeout, **kwargs) as client:
            logger.debug(f"Fetching direct: {url}")
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response
    except Exception as e:
        logger.error(f"Direct connection also failed for {url}: {e}")
        raise


async def test_socks5_proxy(proxy_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Test SOCKS5 proxy connectivity.

    Args:
        proxy_url: Proxy URL to test (uses configured if not provided)

    Returns:
        Dict with test results: {
            'status': 'ok' | 'error',
            'message': str,
            'proxy': str,
            'latency_ms': float
        }
    """
    if proxy_url is None:
        proxy_url = get_socks5_proxy_url()

    if not proxy_url:
        return {
            'status': 'error',
            'message': 'No SOCKS5 proxy configured',
            'proxy': None
        }

    try:
        # Try to connect to a stable test URL
        test_url = "https://www.google.com"
        import time as time_module

        start = time_module.time()

        async with create_httpx_client(proxy_url=proxy_url, timeout=10.0) as client:
            response = await client.get(test_url, follow_redirects=True)
            response.raise_for_status()

        latency_ms = (time_module.time() - start) * 1000

        return {
            'status': 'ok',
            'message': f'Proxy connection successful (latency: {latency_ms:.0f}ms)',
            'proxy': proxy_url,
            'latency_ms': latency_ms
        }
    except Exception as e:
        logger.error(f"Proxy test failed: {e}")
        return {
            'status': 'error',
            'message': f'Proxy connection failed: {str(e)}',
            'proxy': proxy_url
        }
