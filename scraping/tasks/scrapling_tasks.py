"""Celery task examples that call the `scrapling_backend` adapter.
"""
from celery import shared_task


@shared_task(ignore_result=True)
def fetch_page_with_scrapling(url: str, stealth: bool = False):
    from scraping.backends.scrapling_backend import fetch_html

    html = fetch_html(url, stealth=stealth)
    # In a real task, send `html` to the extraction pipeline or save to storage
    print(f"Fetched {len(html)} bytes from {url} (stealth={stealth})")
    return True
