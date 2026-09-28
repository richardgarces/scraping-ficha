from __future__ import annotations

from typing import Any

DEFAULT_HEADERS = {
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
}


class HttpError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class HttpSession:
    """HTTP/2 session with optional Chrome TLS impersonation."""

    def __init__(self, timeout: float = 30.0, headers: dict[str, str] | None = None) -> None:
        self.timeout = timeout
        self.headers = {**DEFAULT_HEADERS, **(headers or {})}
        self._backend, self._client = self._build()

    def _build(self) -> tuple[str, Any]:
        try:
            from curl_cffi import requests as cffi_requests

            # trust_env=False: Cursor y otros sandboxes inyectan HTTP_PROXY local.
            # curl intenta CONNECT por ese proxy, recibe 403 y fallan las 24 tiendas.
            session = cffi_requests.Session(
                impersonate="chrome",
                timeout=self.timeout,
                trust_env=False,
            )
            session.headers.update(self.headers)
            return "curl_cffi", session
        except Exception:
            import httpx

            client = httpx.Client(
                http2=True,
                headers=self.headers,
                timeout=self.timeout,
                follow_redirects=True,
                trust_env=False,
            )
            return "httpx", client

    def get(self, url: str, params: dict[str, Any] | None = None) -> tuple[int, str, str]:
        return self._send("GET", url, params=params)

    def post(
        self,
        url: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> tuple[int, str, str]:
        return self._send("POST", url, params=params, json_body=json_body)

    def _send(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, str, str]:
        kwargs: dict[str, Any] = {"params": params or {}}
        if json_body is not None:
            kwargs["json"] = json_body
        response = self._client.request(method, url, **kwargs)
        content_type = response.headers.get("content-type", "")
        return response.status_code, content_type, response.text

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            close()
