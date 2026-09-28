from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any

_HTML_TAG = re.compile(r"<[^>]+>")
_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def parse_clp(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, list):
        return parse_clp(value[0]) if value else None
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else None


def parse_money(value: Any) -> int | None:
    """Precio CLP desde número, '1549990.000000' o '$1.549.990'. Ignora 0."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, list):
        return parse_money(value[0] if value else None)
    if isinstance(value, (int, float)):
        amount = int(round(float(value)))
        return amount if amount > 0 else None
    text = str(value).strip()
    if re.fullmatch(r"\d+\.\d+", text):
        amount = int(round(float(text)))
        return amount if amount > 0 else None
    amount = parse_clp(text)
    return amount if amount and amount > 0 else None


def parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def parse_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    digits = re.sub(r"[^\d-]", "", str(value))
    if digits in ("", "-"):
        return None
    return int(digits)


def strip_html(value: Any) -> str | None:
    if not value:
        return None
    text = _HTML_TAG.sub(" ", unescape(str(value)))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def extract_next_data(html: str) -> dict[str, Any]:
    match = _NEXT_DATA.search(html)
    if not match:
        raise ValueError("No se encontró __NEXT_DATA__ en el HTML")
    return json.loads(match.group(1))
