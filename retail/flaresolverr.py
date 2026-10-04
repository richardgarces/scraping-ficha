"""FlareSolverr fallback for Cloudflare challenges in the retail worker."""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


def is_challenge(status: int, headers, body: str) -> bool:
    headers = {key.lower(): value.lower() for key, value in headers.items()}
    return headers.get("cf-mitigated") == "challenge" or (
        status in (200, 403, 429, 503)
        and "cloudflare" in headers.get("server", "")
        and any(
            marker in body[:262144].lower()
            for marker in (
                "/cdn-cgi/challenge-platform/",
                "cf-chl-",
                "just a moment...",
            )
        )
    )


def solve(url: str, endpoint: str) -> dict:
    max_timeout = int(os.environ.get("FLARESOLVERR_MAX_TIMEOUT", "60000"))
    if max_timeout <= 0:
        raise RuntimeError("FLARESOLVERR_MAX_TIMEOUT debe ser positivo")
    endpoint = endpoint.rstrip("/")
    if not endpoint.endswith("/v1"):
        endpoint += "/v1"
    request = Request(
        endpoint,
        data=json.dumps(
            {
                "cmd": "request.get",
                "url": url,
                "maxTimeout": max_timeout,
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with build_opener(ProxyHandler({})).open(
            request, timeout=max_timeout / 1000 + 15
        ) as reply:
            result = json.load(reply)
    except (HTTPError, URLError, ValueError) as exc:
        raise RuntimeError("No se pudo consultar FlareSolverr") from exc
    if result.get("status") != "ok":
        raise RuntimeError(
            f"FlareSolverr: {result.get('message', 'error desconocido')}"
        )
    solution = result.get("solution")
    if not isinstance(solution, dict) or not isinstance(solution.get("response"), str):
        raise RuntimeError("FlareSolverr devolvió una solución inválida")
    status = int(solution.get("status", 200))
    if status >= 400 or is_challenge(
        status, {"server": "cloudflare"}, solution["response"]
    ):
        raise RuntimeError("FlareSolverr no resolvió el desafío")
    return solution
