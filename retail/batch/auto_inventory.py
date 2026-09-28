from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from retail.registry import get_client


AUTO_CATEGORIES = (
    {
        "id": "chileautos-usados",
        "store": "chileautos",
        "title": "Autos usados",
        "url": "https://www.chileautos.cl/vehiculos/autos-veh%C3%ADculo/usado-tipo/",
        "page_param": "page",
    },
    {
        "id": "chileautos-nuevos",
        "store": "chileautos",
        "title": "Autos nuevos",
        "url": "https://www.chileautos.cl/vehiculos/autos-veh%C3%ADculo/nuevo-tipo/",
        "page_param": "page",
    },
    {
        "id": "autocosmos-usados",
        "store": "autocosmos",
        "title": "Autos usados",
        "url": "https://www.autocosmos.cl/auto/usado?seccion=precio-final",
        "page_param": "p",
    },
    {
        "id": "autocosmos-nuevos",
        "store": "autocosmos",
        "title": "Autos nuevos",
        "url": "https://www.autocosmos.cl/auto/nuevo?seccion=precio-final",
        "page_param": "p",
    },
)


def _page_url(url: str, param: str, page: int) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if page > 1:
        query[param] = [str(page)]
    else:
        query.pop(param, None)
    encoded = urlencode([(key, value) for key, values in query.items() for value in values])
    return urlunparse(parsed._replace(query=encoded))


def refresh_auto_inventory(repo: Any, *, delay: float = 1.0) -> dict[str, Any]:
    """Descubre autos nuevos/usados página a página y continúa en la corrida siguiente.

    Así se cubre todo el inventario sin intentar descargar decenas de miles de
    avisos de una sola vez ni provocar bloqueos en los portales.
    """
    pages_per_category = max(1, int(os.environ.get("AUTO_INVENTORY_PAGES_PER_CATEGORY", "1") or 1))
    max_items = max(1, int(os.environ.get("AUTO_INVENTORY_MAX_ITEMS", "60") or 60))
    timeout = max(20.0, float(os.environ.get("AUTO_INVENTORY_TIMEOUT", "35") or 35))
    rows: list[dict[str, Any]] = []
    total = 0
    now = datetime.now(timezone.utc).isoformat()
    clients: dict[str, Any] = {}
    try:
        for category in AUTO_CATEGORIES:
            key = f"auto_inventory_cursor:{category['id']}"
            saved = repo.get_app_setting(key) if hasattr(repo, "get_app_setting") else None
            page = max(1, int((saved or {}).get("next_page") or 1))
            found_count = 0
            error = None
            for _ in range(pages_per_category):
                url = _page_url(category["url"], category["page_param"], page)
                try:
                    client = clients.get(category["store"])
                    if client is None:
                        client = get_client(category["store"], delay=delay, timeout=timeout)
                        clients[category["store"]] = client
                    products = client.scrape(url, max_pages=1, max_items=max_items)
                    if not products:
                        page = 1
                        break
                    repo.upsert_many(
                        products,
                        extra={
                            "catalog_category": category["title"],
                            "batch_grupo": "autos",
                            "vehicle_inventory": True,
                            "last_batch_at": now,
                        },
                    )
                    found_count += len(products)
                    total += len(products)
                    page += 1
                except Exception as exc:
                    error = str(exc)
                    break
            if hasattr(repo, "save_app_setting"):
                repo.save_app_setting(key, {"next_page": page, "last_count": found_count, "last_error": error})
            rows.append(
                {
                    "id": category["id"],
                    "store": category["store"],
                    "category": category["title"],
                    "products": found_count,
                    "next_page": page,
                    "error": error,
                }
            )
    finally:
        for client in clients.values():
            try:
                client.close()
            except Exception:
                pass
    return {"categories": rows, "products": total, "pages_per_category": pages_per_category}
