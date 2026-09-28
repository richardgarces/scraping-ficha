from __future__ import annotations

import time
from typing import Any

from retail.http import HttpSession
from retail.models import Product, Target
from retail.registry import StoreSpec


class StoreClient:
    """Contrato mínimo para agregar una fuente nueva."""

    spec: StoreSpec

    def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.http: HttpSession | None = None
        self._last_request = 0.0

    def open_http(self, headers: dict[str, str] | None = None) -> HttpSession:
        self.http = HttpSession(timeout=self.timeout, headers=headers)
        return self.http

    def throttle(self) -> None:
        if self.delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if self._last_request and elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()

    def parse_target(self, value: str) -> Target:
        raise NotImplementedError

    def scrape(
        self,
        target: str | Target,
        *,
        max_pages: int | None = 1,
        max_items: int | None = None,
        sort: str | None = None,
        detalle: bool = False,
    ) -> list[Product]:
        raise NotImplementedError

    def close(self) -> None:
        if self.http is not None:
            self.http.close()
            self.http = None

    def __enter__(self) -> StoreClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def category_target(self, args: Any) -> Target:
        return Target(
            kind="category",
            category_id=getattr(args, "category_id", None) or getattr(args, "slug", None),
            category_name=getattr(args, "nombre", None) or getattr(args, "category_id", None),
        )
