"""Adapter backend to use Scrapling fetchers inside our `scraping` pipeline.

Provides a minimal sync and async fetch wrapper using Scrapling's `Fetcher`
and `StealthyFetcher`. This is a PoC — error handling, timeouts and proxy
management should be extended for production.
"""
from typing import Optional


def _import_sync_fetchers():
    try:
        from scrapling.fetchers import Fetcher, StealthyFetcher
        return Fetcher, StealthyFetcher
    except Exception:
        return None, None


def _import_async_fetchers():
    try:
        from scrapling.fetchers import AsyncFetcher, AsyncStealthyFetcher

        return AsyncFetcher, AsyncStealthyFetcher
    except Exception:
        return None, None


def fetch_html(url: str, stealth: bool = False, headless: bool = True, **kwargs) -> str:
    """Fetch HTML synchronously using Scrapling.

    Imports the fetchers at call time so the module can be imported even when
    Scrapling isn't installed yet (useful in CI or before installing deps).
    """
    Fetcher, StealthyFetcher = _import_sync_fetchers()
    # Scrapling's Fetcher exposes a `get` method (class-level convenience).
    if stealth and StealthyFetcher is not None and hasattr(StealthyFetcher, "get"):
        page = StealthyFetcher.get(url, headless=headless, **kwargs)
    elif Fetcher is not None and hasattr(Fetcher, "get"):
        page = Fetcher.get(url, **kwargs)
    else:
        raise RuntimeError("Scrapling not available in environment")

    # The Scrapling response offers many accessors; prefer `html` when present.
    return getattr(page, "html", str(page))


async def fetch_html_async(url: str, stealth: bool = False, headless: bool = True, **kwargs) -> str:
    """Async fetch using Scrapling async API if available."""
    AsyncFetcher, AsyncStealthyFetcher = _import_async_fetchers()
    if AsyncFetcher is None:
        raise RuntimeError("Scrapling async fetchers not available")

    if stealth and AsyncStealthyFetcher is not None:
        page = await AsyncStealthyFetcher.fetch(url, headless=headless, **kwargs)  # type: ignore
    else:
        page = await AsyncFetcher.fetch(url, **kwargs)  # type: ignore

    return getattr(page, "html", str(page))
