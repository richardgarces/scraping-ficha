from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

from retail.models import Target

SKU_RE = re.compile(r"^(\d{8,})p?$", re.I)
SKU_IN_PATH_RE = re.compile(r"(\d{10,})p$", re.I)
MPM_RE = re.compile(r"(MPM\d+)", re.I)


def normalize_host(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host in {"www.ripley.cl", "ripley.cl"}:
        return parsed._replace(scheme="https", netloc="simple.ripley.cl").geturl()
    return url


def marketplace_id(*values: str | None) -> str | None:
    for raw in values:
        if not raw:
            continue
        match = MPM_RE.search(str(raw))
        if match:
            return match.group(1).upper()
    return None


def product_url(sku: str, slug: str | None = None, parent_id: str | None = None) -> str:
    mpm = marketplace_id(parent_id, sku, slug)
    if mpm:
        return f"https://simple.ripley.cl/{mpm}"
    sku = sku.rstrip("pP")
    if slug:
        slug = slug.removesuffix(f"-{sku}p").removesuffix(f"-{sku}P")
        return f"https://simple.ripley.cl/{slug}-{sku}p"
    return f"https://simple.ripley.cl/{sku}p"


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[áàä]", "a", text)
    text = re.sub(r"[éèë]", "e", text)
    text = re.sub(r"[íìï]", "i", text)
    text = re.sub(r"[óòö]", "o", text)
    text = re.sub(r"[úùü]", "u", text)
    text = text.replace("ñ", "n")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text


def parse_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        return _from_url(normalize_host(raw))

    mpm = marketplace_id(raw)
    if mpm and " " not in raw and "/" not in raw:
        return Target(kind="product", product_id=mpm)

    sku = SKU_RE.match(raw.replace("-", ""))
    if sku and " " not in raw and "/" not in raw:
        return Target(kind="product", product_id=sku.group(1))

    if "/" in raw and " " not in raw:
        return Target(kind="category", category_id=raw.strip("/"), category_name=raw.strip("/"))

    return Target(kind="search", query=raw)


def _from_url(url: str) -> Target:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    query = parse_qs(parsed.query)

    if parts and parts[0] == "search":
        term = unquote(parts[1]) if len(parts) > 1 else (query.get("term") or [None])[0]
        return Target(kind="search", query=term, raw_url=url)

    if parts:
        mpm = marketplace_id(parts[-1])
        if mpm:
            return Target(kind="product", product_id=mpm, raw_url=url)
        sku_match = SKU_IN_PATH_RE.search(parts[-1])
        if sku_match:
            return Target(kind="product", product_id=sku_match.group(1), raw_url=url)

    if parts:
        slug = "/".join(parts)
        return Target(kind="category", category_id=slug, category_name=parts[-1], raw_url=url)

    return Target(kind="url", raw_url=url)
