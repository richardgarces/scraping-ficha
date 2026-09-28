from __future__ import annotations

import unicodedata
from typing import Any

from retail.batch.rules import Alert

ALLOWED_CHANNELS = {"email", "telegram", "push"}
ALLOWED_KINDS = {"common", "real", "super", "watch", "predictive"}


def normalize_preferences(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    channels = [item for item in data.get("channels", []) if item in ALLOWED_CHANNELS]
    kinds = [item for item in data.get("kinds", ["watch"]) if item in ALLOWED_KINDS]

    def percent(name: str) -> float:
        try:
            return min(100.0, max(0.0, float(data.get(name) or 0)))
        except (TypeError, ValueError):
            return 0.0

    def values(name: str, limit: int = 20) -> list[str]:
        raw_values = data.get(name) or []
        if isinstance(raw_values, str):
            raw_values = raw_values.split(",")
        if not isinstance(raw_values, (list, tuple)):
            return []
        cleaned = [str(item).strip()[:80] for item in raw_values if str(item).strip()]
        return list(dict.fromkeys(cleaned))[:limit]

    region = str(data.get("shipping_region") or "").strip()[:80]

    return {
        "channels": list(dict.fromkeys(channels)),
        "kinds": list(dict.fromkeys(kinds)),
        "min_discount_self": percent("min_discount_self"),
        "min_discount_other_stores": percent("min_discount_other_stores"),
        "email_categories": [item.casefold() for item in values("email_categories", limit=50)],
        "email_min_real_discount": percent("email_min_real_discount"),
        "payment_cards": values("payment_cards"),
        "preferred_sizes": values("preferred_sizes"),
        "shipping_region": region,
    }


def alert_discounts(alert: Alert) -> tuple[float | None, float | None]:
    extra = alert.extra or {}
    own = extra.get("percent")
    if own is None and extra.get("percent_vs_median") is not None:
        own = abs(float(extra["percent_vs_median"]))
    return _float_or_none(own), _float_or_none(extra.get("gap_percent"))


def alert_kind(alert: Alert) -> str:
    if alert.rule.startswith("watch_") or alert.category == "seguimiento":
        return "watch"
    if alert.rule == "common_discount":
        return "common"
    own, other = alert_discounts(alert)
    if max(own or 0, other or 0) > 50:
        return "super"
    if other is not None or "below_median" in alert.rule or (alert.extra or {}).get("level") in {"good", "great"}:
        return "real"
    return "common"


def wants_alert(preferences: Any, alert: Alert, *, channel: str | None = None) -> bool:
    prefs = normalize_preferences(preferences)
    extra = alert.extra or {}
    stock = extra.get("stock")
    if not isinstance(stock, bool) and stock not in (None, ""):
        try:
            if int(float(stock)) <= 0:
                return False
        except (TypeError, ValueError):
            pass
    required_card = str(extra.get("payment_card_name") or "").strip().casefold()
    if extra.get("price_basis") == "card" and required_card:
        available_cards = {item.casefold() for item in prefs["payment_cards"]}
        if required_card not in available_cards:
            return False
    if extra.get("only_extreme_sizes"):
        offered = {str(item).strip().casefold() for item in extra.get("available_variants") or []}
        preferred = {item.casefold() for item in prefs["preferred_sizes"]}
        if not offered or not preferred.intersection(offered):
            return False
    kind = alert_kind(alert)
    if kind not in prefs["kinds"]:
        return False
    if kind == "watch":
        return True
    if channel == "email":
        categories = set(prefs["email_categories"])
        if categories:
            alert_category = _category_key(
                extra.get("notification_category") or alert.category or ""
            )
            if alert_category not in categories:
                return False
    own, other = alert_discounts(alert)
    if channel == "email" and kind in {"real", "super"} and prefs["email_min_real_discount"]:
        real_discount = max(own or 0, other or 0)
        if real_discount < prefs["email_min_real_discount"]:
            return False
    matches = []
    if own is not None:
        matches.append(own >= prefs["min_discount_self"])
    if other is not None:
        matches.append(other >= prefs["min_discount_other_stores"])
    return any(matches) if matches else not (prefs["min_discount_self"] or prefs["min_discount_other_stores"])


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _category_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().casefold())
    return "".join(char for char in text if not unicodedata.combining(char))
