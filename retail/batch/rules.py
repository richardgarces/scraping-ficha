from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from retail.batch.catalog import default_rules_path, load_json


@dataclass(slots=True)
class Alert:
    catalog_id: str
    query: str
    rule: str
    name: str
    store: str
    price: int
    previous_price: int | None
    message: str
    url: str | None
    compare_code: str | None
    extra: dict[str, Any]
    saving: int = 0
    category: str | None = None
    image_url: str | None = None
    price_normal: int | None = None


def load_rules(path=None) -> dict[str, Any]:
    return load_json(path or default_rules_path())


def _in_range(price: int | None, rules: dict[str, Any]) -> bool:
    if price is None:
        return False
    minimum = rules.get("min_price")
    maximum = rules.get("max_price")
    if minimum is not None and price < minimum:
        return False
    if maximum is not None and price > maximum:
        return False
    return True


def detect_offers(result: dict[str, Any], catalog_item: dict[str, Any], rules: dict[str, Any]) -> list[Alert]:
    enabled = set(rules.get("enabled") or [])
    alerts: list[Alert] = []
    groups = result.get("groups") or []
    for group in groups:
        offers = [row for row in (group.get("offers") or []) if _in_range(row.get("price"), rules)]
        if not offers:
            continue
        alerts.extend(_drop_alerts(offers, catalog_item, rules, enabled))
        alerts.extend(_median_alerts(offers, catalog_item, rules, enabled))
        alerts.extend(_gap_alerts(group, offers, catalog_item, rules, enabled))
    return alerts


def notification_offers(result: dict[str, Any], catalog_item: dict[str, Any]) -> list[Alert]:
    """Candidatas sin los umbrales globales; cada cuenta aplica luego los propios."""
    personal_rules = {
        "enabled": ["price_drop_percent", "cross_store_gap", "below_median"],
        "price_drop_percent": 0,
        "cross_store_gap_percent": 0,
        "below_median_percent": 0,
        "ignore_fake_discounts": True,
        "min_price": 0,
        "max_price": None,
    }
    alerts = detect_offers(result, catalog_item, personal_rules)
    for group in result.get("groups") or []:
        for row in group.get("offers") or []:
            price = row.get("price")
            normal = row.get("price_normal")
            if not price or not normal or normal <= price:
                continue
            percent = (normal - price) * 100 / normal
            alerts.append(_alert(
                catalog_item,
                "common_discount",
                row,
                f"{percent:.1f}% de descuento en {row.get('store_title') or row.get('store')}",
                {"previous_price": normal, "percent": round(percent, 2)},
                saving=normal - price,
            ))
    return alerts


def _stats(row: dict[str, Any]) -> dict[str, Any]:
    stats = row.get("price_stats")
    return stats if isinstance(stats, dict) else {}


def _drop_alerts(
    offers: list[dict[str, Any]],
    catalog_item: dict[str, Any],
    rules: dict[str, Any],
    enabled: set[str],
) -> list[Alert]:
    found: list[Alert] = []
    percent_min = float(rules.get("price_drop_percent") or 0)
    amount_min = int(rules.get("price_drop_amount") or 0)
    skip_fake = rules.get("ignore_fake_discounts", True)
    for row in offers:
        previous = row.get("previous_price")
        current = row.get("price")
        delta = row.get("price_delta")
        if previous in (None, 0) or current is None or delta is None or delta >= 0:
            continue
        fake = _stats(row).get("fake_discount")
        if fake and skip_fake:
            continue
        drop = abs(int(delta))
        percent = drop * 100 / previous
        triggered: list[str] = []
        if "price_drop_percent" in enabled and percent >= percent_min:
            triggered.append("price_drop_percent")
        if "price_drop_amount" in enabled and drop >= amount_min:
            triggered.append("price_drop_amount")
        if not triggered:
            continue
        found.append(
            _alert(
                catalog_item,
                "+".join(triggered),
                row,
                f"Bajó {percent:.1f}% (${drop:,}) en {row.get('store_title') or row.get('store')}".replace(",", "."),
                {"previous_price": previous, "drop": drop, "percent": round(percent, 2), "fake_discount": fake},
                saving=drop,
            )
        )
    return found


def _median_alerts(
    offers: list[dict[str, Any]],
    catalog_item: dict[str, Any],
    rules: dict[str, Any],
    enabled: set[str],
) -> list[Alert]:
    if "below_median" not in enabled:
        return []
    percent_min = float(rules.get("below_median_percent") or 0)
    found: list[Alert] = []
    for row in offers:
        stats = _stats(row)
        current = row.get("price")
        median = stats.get("median")
        percent = stats.get("percent_vs_median")
        if current is None or not median or percent is None or percent > -percent_min:
            continue
        if stats.get("points", 0) < 3:
            continue
        saving = int(median) - int(current)
        found.append(
            _alert(
                catalog_item,
                "below_median",
                row,
                (
                    f"${current:,} en {row.get('store_title') or row.get('store')}, "
                    f"{abs(percent):.0f}% bajo su precio habitual (${int(median):,})"
                ).replace(",", "."),
                {"median": int(median), "percent_vs_median": percent, "window_days": 90},
                saving=saving,
            )
        )
    return found


def _gap_alerts(
    group: dict[str, Any],
    offers: list[dict[str, Any]],
    catalog_item: dict[str, Any],
    rules: dict[str, Any],
    enabled: set[str],
) -> list[Alert]:
    if "cross_store_gap" not in enabled or not group.get("comparable"):
        return []
    raw_confidence = group.get("entity_confidence")
    if raw_confidence is None:
        codes = [str(row.get("compare_code") or "") for row in group.get("offers") or []]
        raw_confidence = 1.0 if codes and all(code.startswith(("ean:", "manual:")) for code in codes) else (
            0.9 if codes and all(code.startswith("id:") for code in codes) else 0.65
        )
    try:
        confidence = float(raw_confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < 0.80:
        return []
    raw_priced = [row for row in offers if row.get("price")]
    use_landed = bool(raw_priced) and all(row.get("shipping_cost") is not None for row in raw_priced)

    def comparable_price(row: dict[str, Any]) -> int:
        return int(row["price"]) + (int(row.get("shipping_cost") or 0) if use_landed else 0)

    priced = sorted(raw_priced, key=comparable_price)
    if len({row.get("store") for row in priced}) < 2:
        return []
    lowest = priced[0]
    second = next((row for row in priced if row.get("store") != lowest.get("store")), None)
    if second is None:
        return []
    lowest_value = comparable_price(lowest)
    second_value = comparable_price(second)
    gap = second_value - lowest_value
    percent = gap * 100 / second_value if second_value else 0
    if percent < float(rules.get("cross_store_gap_percent") or 0):
        return []
    return [
        _alert(
            catalog_item,
            "cross_store_gap",
            lowest,
            (
                f"Menor {'costo total' if use_landed else 'precio'} ${lowest_value:,} en {lowest.get('store_title') or lowest.get('store')}, "
                f"{percent:.1f}% bajo {second.get('store_title') or second.get('store')}"
            ).replace(",", "."),
            {
                "second_store": second.get("store"),
                "second_price": second.get("price"),
                "second_total": second_value if use_landed else None,
                "comparison_basis": "landed_price" if use_landed else "product_price",
                "entity_confidence": confidence,
                "entity_match_method": group.get("entity_match_method"),
                "gap_percent": round(percent, 2),
            },
            saving=gap,
        )
    ]


def watch_alerts(result: dict[str, Any], watch: dict[str, Any]) -> list[Alert]:
    """Avisa ante cualquier cambio o, para seguimientos antiguos, al cumplir su objetivo."""
    target = watch.get("target_price")
    drop_percent = watch.get("drop_percent")
    code = watch.get("compare_code")
    item = {"id": f"watch:{watch.get('id') or ''}", "query": watch.get("query") or "", "category": "seguimiento"}
    best: dict[str, Any] | None = None
    for group in result.get("groups") or []:
        if code and group.get("compare_code") != code:
            continue
        for row in group.get("offers") or []:
            if row.get("price") and (best is None or row["price"] < best["price"]):
                best = row
    if best is None:
        return []
    price = int(best["price"])
    if watch.get("watch_changes") or (not target and not drop_percent):
        previous = watch.get("last_seen_price")
        if previous is None or int(previous) == price:
            return []
        previous = int(previous)
        direction = "bajó" if price < previous else "subió"
        return [
            _alert(
                item,
                "watch_change",
                {**best, "previous_price": previous},
                (
                    f"{watch.get('name') or best.get('name')} {direction} de ${previous:,} a ${price:,} "
                    f"en {best.get('store_title') or best.get('store')}"
                ).replace(",", "."),
                {"previous_price": previous, "direction": direction},
                saving=max(0, previous - price),
            )
        ]
    if target and price <= int(target):
        saving = max(0, int(target) - price)
        return [
            _alert(
                item,
                "watch_target",
                best,
                (
                    f"{watch.get('name') or best.get('name')} está en ${price:,} "
                    f"en {best.get('store_title') or best.get('store')}, bajo tu objetivo de ${int(target):,}"
                ).replace(",", "."),
                {"target_price": int(target)},
                saving=saving,
            )
        ]
    if drop_percent:
        stats = _stats(best)
        percent = stats.get("percent_vs_median")
        median = stats.get("median")
        if percent is not None and median and percent <= -float(drop_percent):
            return [
                _alert(
                    item,
                    "watch_target",
                    best,
                    (
                        f"{watch.get('name') or best.get('name')} bajó {abs(percent):.0f}% "
                        f"respecto de su precio habitual (${int(median):,})"
                    ).replace(",", "."),
                    {"drop_percent": float(drop_percent), "median": int(median)},
                    saving=max(0, int(median) - price),
                )
            ]
    return []


def _alert(
    catalog_item: dict[str, Any],
    rule: str,
    row: dict[str, Any],
    message: str,
    extra: dict[str, Any],
    saving: int = 0,
) -> Alert:
    stats = _stats(row)
    return Alert(
        catalog_id=str(catalog_item.get("id") or ""),
        query=str(catalog_item.get("query") or ""),
        rule=rule,
        name=str(row.get("name") or catalog_item.get("query") or ""),
        store=str(row.get("store") or ""),
        price=int(row.get("price") or 0),
        previous_price=row.get("previous_price"),
        message=message,
        url=row.get("url"),
        compare_code=row.get("compare_code"),
        extra={
            **extra,
            "product_id": row.get("product_id"),
            "level": stats.get("level"),
            "store_title": row.get("store_title"),
            "display_store": row.get("display_store"),
            "seller": row.get("seller"),
            "condition": row.get("condition"),
            "stock": row.get("stock"),
            "low_stock": bool(row.get("low_stock")),
            "only_extreme_sizes": bool(row.get("only_extreme_sizes")),
            "available_variants": [
                item.get("name")
                for item in row.get("variants") or []
                if isinstance(item, dict) and item.get("available") is not False and item.get("name")
            ],
            "price_basis": "all_payment",
            "price_card": row.get("price_card") or row.get("price_cmr"),
            "payment_card_name": row.get("payment_card_name"),
            "shipping_cost": row.get("shipping_cost"),
            "shipping_free_threshold": row.get("shipping_free_threshold"),
            "shipping_region": row.get("shipping_region"),
            "pickup_available": row.get("pickup_available"),
        },
        saving=max(0, int(saving)),
        category=catalog_item.get("category"),
        image_url=str(row.get("image_url") or "").strip() or None,
        price_normal=row.get("price_normal"),
    )
