"""Miniaturas de producto guardadas en MongoDB como base64."""

from __future__ import annotations

import base64
import io
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from retail.http import DEFAULT_HEADERS

MAX_SIDE = int(os.environ.get("RETAIL_THUMB_SIDE", "240"))
MAX_DOWNLOAD = 4 * 1024 * 1024
MAX_STORED = 120 * 1024
WORKERS = max(1, int(os.environ.get("RETAIL_THUMB_WORKERS", "2") or 2))
IMAGE_HEADERS = {**DEFAULT_HEADERS, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}


def enabled() -> bool:
    return os.environ.get("RETAIL_THUMBS", "1") not in {"0", "false", "no"}


def default_limit() -> int:
    return int(os.environ.get("RETAIL_THUMB_LIMIT", "24"))


def fetch_bytes(url: str, timeout: float = 10.0) -> tuple[bytes, str] | None:
    import httpx

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=IMAGE_HEADERS) as client:
            response = client.get(url)
            if response.status_code != 200:
                return None
            mime = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
            if not mime.startswith("image/"):
                return None
            data = response.content
            if not data or len(data) > MAX_DOWNLOAD:
                return None
            return data, mime
    except Exception:
        return None


def shrink(data: bytes, mime: str, max_side: int = MAX_SIDE) -> tuple[bytes, str, int, int] | None:
    """Reduce la imagen a un cuadro de max_side. Sin Pillow, deja el original si es chico."""
    try:
        from PIL import Image
    except ImportError:
        if len(data) <= MAX_STORED:
            return data, mime, 0, 0
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            image = image.convert("RGB")
            image.thumbnail((max_side, max_side))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=72, optimize=True)
            return buffer.getvalue(), "image/jpeg", image.width, image.height
    except Exception:
        return None


def build_thumbnail(url: str) -> dict[str, Any] | None:
    if not url:
        return None
    downloaded = fetch_bytes(url)
    if downloaded is None:
        return None
    shrunk = shrink(*downloaded)
    if shrunk is None:
        return None
    payload, mime, width, height = shrunk
    if len(payload) > MAX_STORED:
        return None
    return {
        "data": base64.b64encode(payload).decode("ascii"),
        "mime": mime,
        "width": width,
        "height": height,
        "bytes": len(payload),
        "source_url": url,
    }


def build_thumbnail_candidates(urls: list[str]) -> dict[str, Any] | None:
    """Prueba hasta tres imágenes de la galería antes de declarar el fallo."""
    seen: set[str] = set()
    for value in urls[:6]:
        url = str(value or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        thumbnail = build_thumbnail(url)
        if thumbnail:
            return thumbnail
    return None


def build_many_candidates(
    targets: list[tuple[tuple[str, str], list[str]]],
) -> dict[tuple[str, str], dict[str, Any]]:
    if not targets:
        return {}
    found: dict[tuple[str, str], dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(targets))) as pool:
        for (key, _urls), thumbnail in zip(
            targets,
            pool.map(build_thumbnail_candidates, [urls for _, urls in targets]),
        ):
            if thumbnail:
                found[key] = thumbnail
    return found


def build_many(targets: list[tuple[tuple[str, str], str]]) -> dict[tuple[str, str], dict[str, Any]]:
    """targets: [((store, product_id), image_url)] -> miniaturas listas para guardar."""
    if not targets:
        return {}
    found: dict[tuple[str, str], dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(targets))) as pool:
        for key, thumb in zip(
            [key for key, _ in targets],
            pool.map(build_thumbnail, [url for _, url in targets]),
        ):
            if thumb:
                found[key] = thumb
    return found


def decode(thumbnail: dict[str, Any] | None) -> tuple[bytes, str] | None:
    if not thumbnail or not thumbnail.get("data"):
        return None
    try:
        return base64.b64decode(thumbnail["data"]), thumbnail.get("mime") or "image/jpeg"
    except Exception:
        return None
