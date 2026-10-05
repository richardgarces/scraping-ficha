"""Ofertas reales: descuento que se sostiene al comparar tiendas o el historial."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from retail.commercial import condition_group, shipping_comparable
from retail.compare import (
    FAMILY_ORDER,
    STORE_FAMILY,
    collapse_variants,
    identity_match_confidence,
    pack_of,
    same_product_identity,
)
from retail.models import Product
from retail.pricing import parse_moment, series

# El ejemplo del shampoo: 10.000 → 6.000 es 40%. Pedimos al menos 10% para
# no llenar la lista con rebajas de un peso.
MIN_OWN_DISCOUNT = 10.0
# La otra tienda cobra de verdad (precio de venta) cerca del listado de esta.
PEER_AT_LIST = 0.90
# Tiene que ser al menos 10% más cara hoy; si no, no hay brecha.
MIN_SELLING_GAP = 0.10
# Easy y Paris al mismo aviso: 3% de diferencia se toma como el mismo precio.
SAME_PRICE_RATIO = 0.03
# Un día anterior "sin descuento": el precio estaba al 95% o más del normal.
FULL_PRICE_RATIO = 0.95
# Super oferta: supera el 50% vs historial (descuento propio) o vs otra tienda.
MIN_SUPER_PERCENT = 50.0
MIN_ENTITY_CONFIDENCE = 0.80
# Inflación de lista: el «antes» subió fuerte y el precio vuelve cerca del previo.
LIST_INFLATION_WINDOW_DAYS = 30
LIST_INFLATION_RECENT_DAYS = 7
LIST_INFLATION_MIN_RISE = 0.15
LIST_INFLATION_RETURN_RATIO = 0.05
# Ancla cross-store: oferta ≥ mediana/mínimo de pares → no es gran ahorro real.
CROSS_STORE_SIMILAR_RATIO = 0.03
# Pre-evento / Cyber CL: alza sistemática en la ventana previa al evento.
PRE_EVENT_LOOKBACK_DAYS = 14
PRE_EVENT_MIN_RISE = 0.10
# Ventanas habituales Chile (heurística; no calendario oficial cerrado).
# Mayo–junio: Cyber Day / Cyber Mayo. Fin sep–oct: Cyber Monday. Fin nov: Black Friday.
CHILE_EVENT_WINDOWS: tuple[tuple[int, int, int, int, str], ...] = (
    (5, 20, 6, 15, "Cyber Day / Cyber Mayo"),
    (9, 25, 10, 10, "Cyber Monday / Cyber Octubre"),
    (11, 20, 12, 5, "Black Friday / Cyber Noviembre"),
)
# Texto que delata sin stock en nombre/estado (scrapers a veces lo meten en el título).
_AGOTADO_FIELDS = ("name", "title", "availability", "status", "stock_status", "availability_status")


def is_agotado(item: dict[str, Any] | None) -> bool:
    """True si el aviso indica Agotado (o sin stock) en nombre/estado."""
    if not item:
        return False
    stock = item.get("stock")
    if not isinstance(stock, bool) and stock not in (None, ""):
        try:
            if int(float(stock)) <= 0:
                return True
        except (TypeError, ValueError):
            pass
    blob = " ".join(str(item.get(key) or "") for key in _AGOTADO_FIELDS).lower()
    if "agotado" in blob:
        return True
    # Variante clara de stock; no usamos "no disponible" (demasiado genérico en UI).
    return "sin stock" in blob


def is_super_offer(card: dict[str, Any] | None, threshold: float = MIN_SUPER_PERCENT) -> bool:
    """Oferta real cuya brecha o descuento supera el umbral (por defecto > 50%)."""
    if not card:
        return False
    kinds = set(card.get("kinds") or [])
    if not kinds.intersection({"comparacion", "historial"}):
        return False
    gap = float(card.get("gap_percent") or 0)
    discount = max(
        float(card.get("discount") or 0),
        float(card.get("verified_discount") or 0),
    )
    return gap > threshold or discount > threshold


def own_discount_percent(item: dict[str, Any]) -> float:
    normal = _int(item.get("price_normal"))
    price = _int(item.get("price"))
    if not normal or not price or normal <= price:
        return 0.0
    return round((normal - price) * 100 / normal, 1)


def verified_discount_percent(item: dict[str, Any]) -> float:
    """Baja contra precios realmente observados, no contra el 'antes' de vitrina."""
    current = _int(item.get("price"))
    rows = series(item.get("price_history"))
    previous = [price for _moment, price in rows if price and price != current]
    if not current or len(previous) < 2:
        return 0.0
    reference = median(previous[-30:])
    if reference <= current:
        return 0.0
    return round((reference - current) * 100 / reference, 1)


def normal_series(points: list[dict[str, Any]] | None) -> list[tuple[datetime | None, int]]:
    """Pares (fecha, precio_normal) del historial, sin inventar listados."""
    rows: list[tuple[datetime | None, int]] = []
    for entry in points or []:
        if not isinstance(entry, dict):
            continue
        normal = _int(entry.get("price_normal"))
        if not normal:
            continue
        rows.append((parse_moment(entry.get("scraped_at")), normal))
    rows.sort(key=lambda item: item[0] or datetime.min.replace(tzinfo=timezone.utc))
    return rows


def chile_event_label(moment: datetime | None = None) -> str | None:
    """Etiqueta de ventana Cyber/Black Friday CL si ``moment`` cae dentro."""
    from zoneinfo import ZoneInfo

    stamp = moment or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    local = stamp.astimezone(ZoneInfo("America/Santiago"))
    month, day = local.month, local.day
    for start_m, start_d, end_m, end_d, label in CHILE_EVENT_WINDOWS:
        after_start = (month > start_m) or (month == start_m and day >= start_d)
        before_end = (month < end_m) or (month == end_m and day <= end_d)
        if start_m <= end_m:
            if after_start and before_end:
                return label
        elif after_start or before_end:
            return label
    return None


def detect_list_inflation(
    item: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Lista inflada: el «antes» subió fuerte y el precio vuelve cerca del previo.

    Ejemplo: normal 10.000 → 14.000 en <30 días, oferta a 10.200 (−27% comercial)
    pero vs el precio de venta habitual el ahorro real ≈ 0.
    """
    current = _int(item.get("price"))
    current_normal = _int(item.get("price_normal"))
    if not current or not current_normal or current_normal <= current:
        return None
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    window_start = stamp - timedelta(days=LIST_INFLATION_WINDOW_DAYS)
    recent_cut = stamp - timedelta(days=LIST_INFLATION_RECENT_DAYS)

    normals = [
        (moment or stamp, value)
        for moment, value in normal_series(item.get("price_history"))
        if value and (moment is None or moment >= window_start)
    ]
    if current_normal:
        normals.append((stamp, current_normal))
    if len(normals) < 2:
        return None

    older = [value for moment, value in normals if moment < recent_cut]
    recent = [value for moment, value in normals if moment >= recent_cut]
    if len(older) < 1 or not recent:
        # Sin corte de 7 días: usa la primera mitad del historial de lista.
        midpoint = max(1, len(normals) // 2)
        older = [value for _, value in normals[:midpoint]]
        recent = [value for _, value in normals[midpoint:]]
    if not older or not recent:
        return None

    baseline_normal = int(round(median(older)))
    peak_normal = max(recent)
    if baseline_normal <= 0 or peak_normal < baseline_normal * (1 + LIST_INFLATION_MIN_RISE):
        return None
    if current_normal < baseline_normal * (1 + LIST_INFLATION_MIN_RISE):
        return None

    selling = series(item.get("price_history"))
    prior_selling = [
        price
        for moment, price in selling
        if price and (moment is None or moment < recent_cut)
    ]
    if len(prior_selling) < 1:
        prior_selling = [price for moment, price in selling[:-1] if price] if len(selling) > 1 else []
    if not prior_selling:
        prior_selling = [baseline_normal]
    prior_ref = int(round(median(prior_selling[-30:])))
    # El «descuento» vuelve cerca del precio de venta previo (o del normal viejo).
    near_prior = abs(current - prior_ref) / max(prior_ref, 1) <= LIST_INFLATION_RETURN_RATIO
    near_old_list = abs(current - baseline_normal) / max(baseline_normal, 1) <= LIST_INFLATION_RETURN_RATIO
    if not near_prior and not near_old_list:
        # Todavía más barato de verdad vs el previo: no es solo vitrina.
        if current < prior_ref * (1 - LIST_INFLATION_RETURN_RATIO):
            return None
        return None

    commercial = round((current_normal - current) * 100 / current_normal, 1)
    if near_prior or near_old_list:
        real_vs_prior = 0.0
    elif prior_ref > current:
        real_vs_prior = round((prior_ref - current) * 100 / prior_ref, 1)
    else:
        real_vs_prior = 0.0
    return {
        "kind": "list_inflation",
        "baseline_normal": baseline_normal,
        "inflated_normal": peak_normal,
        "prior_selling": prior_ref,
        "rise_percent": round((peak_normal - baseline_normal) * 100 / baseline_normal, 1),
        "commercial_discount": commercial,
        "real_savings_percent": real_vs_prior,
        "label": "infló el precio de lista",
    }


def detect_pre_event_inflation(
    item: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Subida de lista o de venta en los ~14 días previos a una ventana Cyber CL."""
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    event = chile_event_label(stamp)
    # Mira ~28 días: baseline temprana vs pico previo al «descuento» actual.
    window_start = stamp - timedelta(days=PRE_EVENT_LOOKBACK_DAYS + 14)
    inflate_start = stamp - timedelta(days=PRE_EVENT_LOOKBACK_DAYS)
    inflate_end = stamp - timedelta(days=2)

    def _points(kind: str) -> list[tuple[datetime, int]]:
        raw = normal_series(item.get("price_history")) if kind == "normal" else series(item.get("price_history"))
        rows = [
            (moment or stamp, value)
            for moment, value in raw
            if value and (moment is None or moment >= window_start)
        ]
        current_value = _int(item.get("price_normal" if kind == "normal" else "price"))
        if current_value:
            rows.append((stamp, current_value))
        return rows

    def _rise(rows: list[tuple[datetime, int]]) -> dict[str, Any] | None:
        if len(rows) < 2:
            return None
        early = [value for moment, value in rows if moment < inflate_start]
        if not early:
            early = [rows[0][1]]
        peak_rows = [
            value for moment, value in rows
            if inflate_start <= moment <= inflate_end
        ]
        if not peak_rows:
            peak_rows = [value for moment, value in rows if moment < stamp][-3:] or [rows[-1][1]]
        base = int(round(median(early)))
        peak = max(peak_rows)
        if base <= 0 or peak < base * (1 + PRE_EVENT_MIN_RISE):
            return None
        return {
            "baseline": base,
            "peak": peak,
            "rise_percent": round((peak - base) * 100 / base, 1),
        }

    normal_rise = _rise(_points("normal"))
    selling_rise = _rise(_points("selling"))
    chosen = normal_rise or selling_rise
    if not chosen:
        return None
    current = _int(item.get("price"))
    current_normal = _int(item.get("price_normal"))
    prior = chosen["baseline"]
    if current and current < prior * (1 - LIST_INFLATION_RETURN_RATIO):
        return None
    commercial = 0.0
    if current and current_normal and current_normal > current:
        commercial = round((current_normal - current) * 100 / current_normal, 1)
    if commercial < MIN_OWN_DISCOUNT and not event:
        return None
    label = event or "precio subió antes del descuento"
    return {
        "kind": "pre_event_inflation",
        "event": event,
        "baseline": chosen["baseline"],
        "peak": chosen["peak"],
        "rise_percent": chosen["rise_percent"],
        "commercial_discount": commercial,
        "label": f"subió {chosen['rise_percent']:.0f}% antes de {label}",
    }


def cross_store_anchor(
    item: dict[str, Any],
    peers: list[dict[str, Any]],
    *,
    entity_confidence: float,
) -> dict[str, Any] | None:
    """Ancla el «ahorro real» vs mediana/mínimo de otras tiendas (confianza ≥ 80%)."""
    if entity_confidence < MIN_ENTITY_CONFIDENCE:
        return None
    price = _selling_price(item)
    others = [_selling_price(peer) for peer in peers if _selling_price(peer)]
    if not price or len(others) < 1:
        return None
    peer_min = min(others)
    peer_med = int(round(median(others)))
    vs_min = peer_min - price
    vs_med = peer_med - price
    similar_to_min = price >= peer_min * (1 - CROSS_STORE_SIMILAR_RATIO)
    similar_to_median = price >= peer_med * (1 - CROSS_STORE_SIMILAR_RATIO)
    similar = similar_to_min or similar_to_median
    return {
        "peer_min": peer_min,
        "peer_median": peer_med,
        "gap_vs_min": vs_min,
        "gap_vs_median": vs_med,
        "real_savings_vs_median": max(0, vs_med),
        "real_savings_percent": round(vs_med * 100 / peer_med, 1) if peer_med and vs_med > 0 else 0.0,
        "similar_to_market": similar,
        "label": (
            "precio similar a otras tiendas"
            if similar
            else f"ahorro real vs mediana de otras tiendas: {max(0, vs_med):,}".replace(",", ".")
        ),
    }


def offer_integrity(
    item: dict[str, Any],
    peers: list[dict[str, Any]],
    *,
    entity_confidence: float,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Señales de vitrina vs ahorro real; no inventa datos si falta historial/pares."""
    commercial = own_discount_percent(item)
    verified = verified_discount_percent(item)
    list_inflate = detect_list_inflation(item, now=now)
    pre_event = detect_pre_event_inflation(item, now=now)
    anchor = cross_store_anchor(item, peers, entity_confidence=entity_confidence)
    flags: list[str] = []
    if list_inflate:
        flags.append("list_inflation")
    if pre_event:
        flags.append("pre_event_inflation")
    if anchor and anchor.get("similar_to_market"):
        flags.append("similar_to_market")
    real_savings_percent = verified
    if anchor and not anchor.get("similar_to_market"):
        real_savings_percent = max(real_savings_percent, float(anchor.get("real_savings_percent") or 0))
    if list_inflate:
        real_savings_percent = min(
            real_savings_percent,
            float(list_inflate.get("real_savings_percent") or 0),
        )
    suspicious = bool(flags) and (
        list_inflate is not None
        or (anchor and anchor.get("similar_to_market") and commercial >= MIN_OWN_DISCOUNT)
        or (pre_event is not None and commercial >= MIN_OWN_DISCOUNT and verified < MIN_OWN_DISCOUNT)
    )
    reasons = []
    if list_inflate:
        reasons.append(list_inflate["label"])
    if pre_event:
        reasons.append(pre_event["label"])
    if anchor and anchor.get("similar_to_market"):
        reasons.append(anchor["label"])
    return {
        "commercial_discount": commercial,
        "verified_discount": verified,
        "real_savings_percent": round(real_savings_percent, 1),
        "list_inflation": list_inflate,
        "pre_event_inflation": pre_event,
        "cross_store": anchor,
        "suspicion_flags": flags,
        "suspicious": suspicious,
        "suspicion_labels": reasons,
    }


def entity_confidence_of(item: dict[str, Any]) -> float:
    """Confianza guardada o heurística por prefijo; preferir ``group_entity_confidence``."""
    try:
        if item.get("entity_confidence") is not None:
            return max(0.0, min(1.0, float(item["entity_confidence"])))
    except (TypeError, ValueError):
        pass
    code = str(item.get("compare_code") or "")
    if code.startswith(("ean:", "manual:")):
        return 1.0
    if code.startswith("id:"):
        return 0.9
    return 0.65


def group_entity_confidence(items: list[dict[str, Any]]) -> float:
    """Confianza entre pares por nombre/identidad, no por SKU de cada tienda.

    El historial de la misma tienda no pasa por aquí: solo se usa al armar la
    brecha o el mismo precio entre comercios.
    """
    if not items:
        return 0.0
    if len(items) == 1:
        return entity_confidence_of(items[0])
    products = [Product.from_dict(item) for item in items]
    best_per_item: list[float] = []
    for index, item in enumerate(products):
        scores = [
            identity_match_confidence(item, other)[0]
            for pos, other in enumerate(products)
            if pos != index
        ]
        best_per_item.append(max(scores, default=0.0))
    return round(min(best_per_item), 3) if best_per_item else 0.0


def previous_full_price_day(
    history: list[dict[str, Any]] | None,
    current_price: int | None,
    normal: int | None,
) -> str | None:
    """Día anterior en que el producto se vendió sin descuento (cerca del normal)."""
    if not current_price or not normal:
        return None
    rows = series(history)
    if len(rows) < 2:
        return None
    last_moment, last_price = rows[-1]
    current_day = last_moment.date() if last_moment else None
    for moment, price in reversed(rows[:-1] if last_price == current_price else rows):
        if price == current_price:
            continue
        day = moment.date() if moment else None
        if current_day and day == current_day:
            continue
        if price >= normal * FULL_PRICE_RATIO:
            return day.isoformat() if day else "antes"
    return None


def prices_are_same(left: dict[str, Any], right: dict[str, Any]) -> bool:
    first = _int(left.get("price"))
    second = _int(right.get("price"))
    if not first or not second:
        return False
    high, low = max(first, second), min(first, second)
    return (high - low) / high <= SAME_PRICE_RATIO


def collapse_sisters(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Easy/Paris (o Falabella/Sodimac) al mismo precio de venta son un solo aviso."""
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    leftover: list[dict[str, Any]] = []
    for row in rows:
        family = STORE_FAMILY.get(row.get("store") or "")
        if not family:
            leftover.append(row)
            continue
        buckets[family].append(row)

    collapsed = list(leftover)
    for group in buckets.values():
        group.sort(
            key=lambda row: (
                _int(row.get("price")) or 10**12,
                FAMILY_ORDER.get(row.get("store") or "", 9),
            )
        )
        clusters: list[list[dict[str, Any]]] = []
        for row in group:
            placed = False
            for cluster in clusters:
                if prices_are_same(cluster[0], row):
                    cluster.append(row)
                    placed = True
                    break
            if not placed:
                clusters.append([row])
        for cluster in clusters:
            best = dict(cluster[0])
            if len(cluster) > 1:
                best["mirrors"] = {"stores": [item.get("store") for item in cluster[1:]]}
            collapsed.append(best)
    return collapsed


def collapse_store_prices(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Una fila por tienda y envase: 16 comprimidos no se mezcla con 20 de la misma tienda."""
    buckets: dict[tuple[str, tuple[str, ...]], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[(str(row.get("store") or ""), pack_of(row))].append(row)
    collapsed: list[dict[str, Any]] = []
    for group in buckets.values():
        group.sort(key=lambda row: _int(row.get("price")) or 10**12)
        collapsed.append(dict(group[0]))
    collapsed.sort(key=lambda row: _int(row.get("price")) or 10**12)
    return collapsed


def pick_real_offer(
    offers: list[dict[str, Any]],
    *,
    comparacion: bool = True,
    historial: bool = True,
    iguales: bool = False,
) -> dict[str, Any] | None:
    """El mejor aviso del grupo de pares (mismo producto por nombre) pedido."""
    if not comparacion and not historial and not iguales:
        return None
    shown = [
        item
        for item in collapse_variants(offers)
        if _int(item.get("price")) and not is_agotado(item)
    ]
    ranked: list[dict[str, Any]] = []
    by_pack: dict[tuple[tuple[str, ...], str], list[dict[str, Any]]] = defaultdict(list)
    for item in shown:
        by_pack[(pack_of(item), condition_group(item.get("condition")))].append(item)
    for group in by_pack.values():
        # Pares entre tiendas por identidad de nombre/atributos. Los códigos
        # internos (product_id/sku) no definen el grupo: cambian por comercio.
        identity_groups: list[list[dict[str, Any]]] = []
        for item in group:
            target = next(
                (
                    cluster for cluster in identity_groups
                    if any(same_product_identity(item, peer) for peer in cluster)
                ),
                None,
            )
            if target is None:
                identity_groups.append([item])
            else:
                target.append(item)
        for identity_group in identity_groups:
            card = _score_pack_group(
                identity_group,
                comparacion=comparacion,
                historial=historial,
                iguales=iguales,
            )
            if card and not is_agotado(card):
                ranked.append(card)
    if not ranked:
        return None
    ranked.sort(key=lambda row: (
        -(row.get("offer_score") or 0),
        -(row.get("gap") or 0),
        -(row.get("gap_percent") or 0),
    ))
    return ranked[0]


def _score_pack_group(
    shown: list[dict[str, Any]],
    *,
    comparacion: bool,
    historial: bool,
    iguales: bool,
) -> dict[str, Any] | None:
    by_store = collapse_store_prices(shown)
    priced = [item for item in collapse_sisters(by_store) if _int(item.get("price"))]
    use_landed = shipping_comparable(priced)
    if use_landed:
        for item in priced:
            item["_comparison_price"] = (_int(item.get("price")) or 0) + (_int(item.get("shipping_cost")) or 0)
    if len({item.get("store") for item in by_store}) < 2:
        return None
    # Confianza por similitud de nombre/identidad entre tiendas, no por el
    # compare_code/SKU guardado (que suele ser distinto en cada comercio).
    entity_confidence = group_entity_confidence(priced)
    if entity_confidence < MIN_ENTITY_CONFIDENCE:
        return None

    best_price_item = min(priced, key=_selling_price)
    published_winner = max(priced, key=own_discount_percent)
    verified_winner = max(priced, key=verified_discount_percent)

    ranked: list[dict[str, Any]] = []
    for item in priced:
        discount = own_discount_percent(item)
        verified_discount = verified_discount_percent(item)
        if discount < MIN_OWN_DISCOUNT and verified_discount < MIN_OWN_DISCOUNT:
            continue
        peers = [peer for peer in priced if peer.get("store") != item.get("store") and _int(peer.get("price"))]
        integrity = offer_integrity(item, peers, entity_confidence=entity_confidence)
        # Inflación de lista o precio igual al mercado: no vender el −X% comercial
        # como oferta real. Solo pasa si hay baja verificada genuina vs historial
        # y además queda bajo la mediana de otras tiendas.
        if integrity.get("list_inflation") or integrity.get("pre_event_inflation"):
            genuine = (
                float(integrity.get("real_savings_percent") or 0) >= MIN_OWN_DISCOUNT
                and not (integrity.get("cross_store") or {}).get("similar_to_market")
            )
            if not genuine:
                continue
        if (integrity.get("cross_store") or {}).get("similar_to_market"):
            # Sin brecha real vs el mercado: el cartel no basta.
            if verified_discount < MIN_OWN_DISCOUNT:
                continue
        kinds: list[str] = []
        list_peers = _peers_at_list(item, peers)
        if comparacion and list_peers and not (integrity.get("cross_store") or {}).get("similar_to_market"):
            kinds.append("comparacion")
        was_on = previous_full_price_day(
            item.get("price_history"),
            _int(item.get("price")),
            _int(item.get("price_normal")),
        )
        # Si solo «estuvo a precio lleno» porque inflaron la lista, no cuenta.
        history_ok = bool(was_on) and not integrity.get("list_inflation")
        if historial and (history_ok or verified_discount >= MIN_OWN_DISCOUNT):
            if integrity.get("list_inflation") and verified_discount < MIN_OWN_DISCOUNT:
                pass
            else:
                kinds.append("historial")
        if iguales and not kinds and _same_price_listing(item, by_store):
            kinds.append("iguales")
        if not kinds:
            continue
        rival = _cheapest_other(item, priced) or _cheapest_other(item, by_store)
        if rival is None:
            continue
        gap = _selling_price(rival) - _selling_price(item)
        if "iguales" in kinds and "comparacion" not in kinds and "historial" not in kinds:
            gap = max(0, gap)
        elif gap <= 0 and "historial" not in kinds:
            continue
        ranked.append(
            _card(
                item, peers=by_store, kinds=kinds, rival=rival, gap=gap,
                was_on=was_on if history_ok else None,
                discount=discount, entity_confidence=entity_confidence,
                best_price_item=best_price_item, published_winner=published_winner,
                verified_winner=verified_winner, integrity=integrity,
            )
        )

    if not ranked:
        return None
    ranked.sort(key=lambda row: (-(row.get("gap") or 0), -(row.get("gap_percent") or 0)))
    return ranked[0]


def _same_price_listing(item: dict[str, Any], shown: list[dict[str, Any]]) -> bool:
    others = [row for row in shown if row.get("store") != item.get("store")]
    if not others:
        return False
    return all(prices_are_same(item, row) for row in others)


def _cheapest_other(item: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    others = [row for row in rows if row.get("store") != item.get("store") and _int(row.get("price"))]
    if not others:
        return None
    return min(others, key=lambda row: _selling_price(row) or 10**12)


def _selling_price(item: dict[str, Any]) -> int:
    return _int(item.get("_comparison_price")) or _int(item.get("price")) or 0


def _peers_at_list(item: dict[str, Any], peers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Otra tienda que *cobra* cerca del precio normal de esta (no el 'antes' de vitrina)."""
    normal = _int(item.get("price_normal"))
    price = _int(item.get("price"))
    if not normal or not price:
        return []
    floor_list = normal * PEER_AT_LIST
    floor_gap = price * (1 + MIN_SELLING_GAP)
    found = []
    for peer in peers:
        selling = _selling_price(peer)
        if selling >= floor_list and selling >= floor_gap:
            found.append(peer)
    return found


def _peers_more_expensive(item: dict[str, Any], peers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    price = _selling_price(item)
    if not price:
        return []
    floor = price * (1 + MIN_SELLING_GAP)
    return [peer for peer in peers if _selling_price(peer) >= floor]


def _card(
    item: dict[str, Any],
    *,
    peers: list[dict[str, Any]],
    kinds: list[str],
    rival: dict[str, Any],
    gap: int,
    was_on: str | None,
    discount: float,
    entity_confidence: float,
    best_price_item: dict[str, Any],
    published_winner: dict[str, Any],
    verified_winner: dict[str, Any],
    integrity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    price = _int(item.get("price")) or 0
    normal = _int(item.get("price_normal"))
    rival_price = _int(rival.get("price")) or 0
    rival_comparison = _selling_price(rival)
    vs_rival = round(gap * 100 / rival_comparison, 1) if rival_comparison else 0.0
    stores = [
        _store_row(
            row,
            win=row.get("store") == item.get("store"),
            best_price=_product_key(row) == _product_key(best_price_item),
            strongest_published=_product_key(row) == _product_key(published_winner),
            strongest_verified=(
                _product_key(row) == _product_key(verified_winner)
                and verified_discount_percent(verified_winner) > 0
            ),
        )
        for row in sorted(peers, key=lambda row: _int(row.get("price")) or 10**12)
    ]
    verified_discount = verified_discount_percent(item)
    market_best = _product_key(item) == _product_key(best_price_item)
    stock_score = 10.0 if item.get("stock_verified") or (
        item.get("stock") not in (None, "") and not is_agotado(item)
    ) else 5.0 if not is_agotado(item) else 0.0
    history_points = len(series(item.get("price_history")))
    signals = integrity or {}
    real_savings = float(signals.get("real_savings_percent") or verified_discount or 0)
    commercial = float(signals.get("commercial_discount") or discount or 0)
    score = round(
        (40.0 if market_best else 0.0)
        + 30.0 * min(1.0, real_savings / 30.0)
        + 15.0 * entity_confidence
        + stock_score
        + 5.0 * min(1.0, history_points / 5.0)
        - (25.0 if signals.get("suspicious") else 0.0)
        - (15.0 if "similar_to_market" in (signals.get("suspicion_flags") or []) else 0.0),
        1,
    )
    return {
        "name": item.get("name"),
        "brand": item.get("brand"),
        "category": item.get("catalog_category") or item.get("category"),
        "compare_code": item.get("compare_code"),
        "kinds": kinds,
        "store": item.get("store"),
        "product_id": item.get("product_id"),
        "url": item.get("url"),
        "has_thumb": bool(item.get("has_thumb")),
        "price": price,
        "total_price": _selling_price(item) if item.get("_comparison_price") else None,
        "price_normal": normal,
        "discount": discount,
        "published_discount": commercial,
        "commercial_discount": commercial,
        "verified_discount": verified_discount,
        "real_savings_percent": real_savings,
        "gap": gap,
        "gap_percent": vs_rival,
        "rival_store": rival.get("store"),
        "rival_price": rival_price,
        "rival_total_price": rival_comparison if rival.get("_comparison_price") else None,
        "comparison_basis": "landed_price" if item.get("_comparison_price") else "product_price",
        "market_best": market_best,
        "best_price_store": best_price_item.get("store"),
        "best_price": _int(best_price_item.get("price")),
        "best_total_price": _selling_price(best_price_item) if best_price_item.get("_comparison_price") else None,
        "strongest_published_store": published_winner.get("store"),
        "strongest_published_discount": own_discount_percent(published_winner),
        "strongest_verified_store": verified_winner.get("store") if verified_discount_percent(verified_winner) > 0 else None,
        "strongest_verified_discount": verified_discount_percent(verified_winner),
        "entity_confidence": entity_confidence,
        "entity_match_method": item.get("entity_match_method"),
        "offer_score": score,
        "was_full_price_on": was_on if "historial" in kinds else None,
        "stores": stores,
        "list_inflation": signals.get("list_inflation"),
        "pre_event_inflation": signals.get("pre_event_inflation"),
        "cross_store": signals.get("cross_store"),
        "suspicion_flags": signals.get("suspicion_flags") or [],
        "suspicion_labels": signals.get("suspicion_labels") or [],
        "reason": _reason(item, rival, kinds, was_on, discount, integrity=signals),
        "updated_at": _iso(item.get("updated_at")),
    }


def _store_row(
    item: dict[str, Any], *, win: bool, best_price: bool = False,
    strongest_published: bool = False, strongest_verified: bool = False,
) -> dict[str, Any]:
    return {
        "store": item.get("store"),
        "product_id": item.get("product_id"),
        "url": item.get("url"),
        "price": _int(item.get("price")),
        "total_price": _selling_price(item) if item.get("_comparison_price") else None,
        "shipping_cost": _int(item.get("shipping_cost")),
        "price_normal": _int(item.get("price_normal")),
        "discount": own_discount_percent(item),
        "published_discount": own_discount_percent(item),
        "commercial_discount": own_discount_percent(item),
        "verified_discount": verified_discount_percent(item),
        "best_price": best_price,
        "strongest_published": strongest_published,
        "strongest_verified": strongest_verified,
        "win": win,
    }


def _product_key(item: dict[str, Any]) -> tuple[str, str]:
    return str(item.get("store") or ""), str(item.get("product_id") or item.get("sku_id") or "")


def _reason(
    item: dict[str, Any],
    rival: dict[str, Any],
    kinds: list[str],
    was_on: str | None,
    discount: float,
    *,
    integrity: dict[str, Any] | None = None,
) -> str:
    store = item.get("store") or "esta tienda"
    other = rival.get("store") or "otra tienda"
    price = _int(item.get("price"))
    normal = _int(item.get("price_normal"))
    rival_price = _int(rival.get("price"))
    parts = []
    signals = integrity or {}
    commercial = float(signals.get("commercial_discount") or discount or 0)
    real = float(signals.get("real_savings_percent") or 0)
    if signals.get("suspicion_labels"):
        parts.append(
            "Cuidado: "
            + "; ".join(signals["suspicion_labels"])
            + f". Descuento comercial {commercial:.0f}% ≠ ahorro real {real:.0f}%."
        )
    if "comparacion" in kinds:
        parts.append(
            f"En {store} cuesta {_clp(price)} "
            f"(descuento comercial {commercial:.0f}% sobre {_clp(normal)}; "
            f"ahorro real ~{real:.0f}%). "
            f"El mismo producto en {other} se vende a {_clp(rival_price)}."
        )
    if "historial" in kinds:
        when = f"el {was_on}" if was_on and was_on != "antes" else "antes"
        parts.append(
            f"En {store} estuvo sin descuento {when} y hoy baja a {_clp(price)}. "
            f"Frente a {other} ({_clp(rival_price)}) el descuento se mantiene."
        )
    if "iguales" in kinds and "comparacion" not in kinds:
        parts.append(
            f"En {store} y {other} el precio de venta es el mismo ({_clp(price)}). "
            f"El {commercial:.0f}% off es el 'antes' de vitrina, no una brecha entre tiendas."
        )
    cross = signals.get("cross_store") or {}
    if cross.get("similar_to_market") and "iguales" not in kinds:
        parts.append(
            f"Precio similar a otras tiendas (mediana {_clp(cross.get('peer_median'))}, "
            f"mínimo {_clp(cross.get('peer_min'))})."
        )
    return " ".join(parts)


def _clp(value: int | None) -> str:
    if value is None:
        return "s/precio"
    return f"${value:,.0f}".replace(",", ".")


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _int(value: Any) -> int | None:
    if value in (None, "", 0):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
