"""HTTP client utilities with realistic browser headers."""

import httpx

from zfrog.config import settings
from zfrog.utils.url_guard import guard_request_hook

# Realistic Chrome headers
CHROME_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}


def create_client(
    proxy: str | None = None,
    timeout_connect: int = 30,
    timeout_read: int = 60,
) -> httpx.AsyncClient:
    """Create an HTTP client with realistic headers.
    
    Args:
        proxy: Optional proxy URL.
        timeout_connect: Connection timeout in seconds.
        timeout_read: Read timeout in seconds.
        
    Returns:
        Configured httpx.AsyncClient.
    """
    timeout = httpx.Timeout(
        connect=timeout_connect,
        read=timeout_read,
        write=30,
        pool=30,
    )
    
    client_kwargs = {
        "headers": CHROME_HEADERS,
        "timeout": timeout,
        "follow_redirects": True,
        "max_redirects": settings.http_max_redirects,
        "verify": True,
        # Runs for every request, including each redirect hop, so a public URL
        # cannot redirect the server into the internal network.
        "event_hooks": {"request": [guard_request_hook]},
    }
    
    if proxy:
        client_kwargs["proxy"] = proxy
    
    return httpx.AsyncClient(**client_kwargs)
