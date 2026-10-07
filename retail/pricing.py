"""Estadísticas de precio sobre el historial guardado en MongoDB."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

WINDOWS = (7, 30, 90)
RECENT_DAYS = 7
INFLATION_MARGIN = 0.05
SANTIAGO = ZoneInfo("America/Santiago")


def parse_moment(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def series(points: list[dict[str, Any]] | None) -> list[tuple[datetime | None, int]]:
    """Pares (fecha, precio) en orden cronológico, sin precios vacíos."""
    rows: list[tuple[datetime | None, int]] = []
    entries = [entry for entry in points or [] if isinstance(entry, dict)]
    # Desde que se distingue el precio para todo medio, no se mezcla con el
    # historial antiguo que podía contener valores exclusivos de tarjeta.
    if any(entry.get("price_basis") == "all_payment" for entry in entries):
        entries = [entry for entry in entries if entry.get("price_basis") == "all_payment"]
    for entry in entries:
        price = entry.get("price")
        if price in (None, 0):
            continue
        rows.append((parse_moment(entry.get("scraped_at")), int(price)))
    rows.sort(key=lambda item: item[0] or datetime.min.replace(tzinfo=timezone.utc))
    return rows


def santiago_day(moment: datetime) -> date:
    """Día calendario en Chile, no el día UTC del timestamp."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(SANTIAGO).date()


def _chart_stamp(day: date) -> str:
    # 16:00 UTC cae en la misma fecha de Santiago con o sin horario de verano.
    return datetime(day.year, day.month, day.day, 16, tzinfo=timezone.utc).isoformat()


def chart_history(
    points: list[dict[str, Any]] | None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Un punto por día (America/Santiago) desde la primera medición hasta hoy.

    El precio se arrastra aunque no haya cambiado, para que la ficha pueda
    dibujar una línea horizontal. Un solo día calendario queda en un punto:
    eso no alcanza para la curva.
    """
    now = now or datetime.now(timezone.utc)
    last_by_day: dict[date, int] = {}
    for moment, price in series(points):
        if moment is None:
            continue
        last_by_day[santiago_day(moment)] = price
    if not last_by_day:
        return []

    start = min(last_by_day)
    today = santiago_day(now)
    if start >= today:
        day = max(last_by_day)
        return [{"price": last_by_day[day], "scraped_at": _chart_stamp(day), "day": day.isoformat()}]

    out: list[dict[str, Any]] = []
    price: int | None = None
    day = start
    while day <= today:
        if day in last_by_day:
            price = last_by_day[day]
        if price is not None:
            out.append({"price": price, "scraped_at": _chart_stamp(day), "day": day.isoformat()})
        day += timedelta(days=1)
    return out


def chart_drawable(points: list[dict[str, Any]] | None, now: datetime | None = None) -> bool:
    """Hay precios en más de un día calendario, aunque el valor no haya cambiado."""
    return len(chart_history(points, now=now)) >= 2


def price_observations(
    points: list[dict[str, Any]] | None,
    *,
    current_offer: Any = None,
    current_normal: Any = None,
    current_at: Any = None,
) -> list[dict[str, Any]]:
    """Observaciones comparables, ordenadas y con una sola fila por día de Santiago.

    Conserva el historial crudo en MongoDB. Para la API elige la última oferta
    válida del día y el último precio normal válido de ese mismo día, sin
    rellenar días sin medición ni arrastrar referencias de fechas anteriores.
    """

    entries = [entry for entry in points or [] if isinstance(entry, dict)]
    if any(entry.get("price_basis") == "all_payment" for entry in entries):
        entries = [entry for entry in entries if entry.get("price_basis") == "all_payment"]

    def valid_price(value: Any) -> int | None:
        if value in (None, "", 0):
            return None
        try:
            price = int(value)
        except (TypeError, ValueError):
            return None
        return price if price > 0 else None

    parsed: list[tuple[datetime, dict[str, Any]]] = []
    for entry in entries:
        moment = parse_moment(entry.get("scraped_at"))
        if moment is not None:
            parsed.append((moment, entry))
    current_moment = parse_moment(current_at)
    parsed.sort(key=lambda item: item[0])
    latest = parsed[-1][1] if parsed else {}
    latest_offer = valid_price(latest.get("price_offer"))
    if latest_offer is None:
        latest_offer = valid_price(latest.get("price"))
    latest_normal = valid_price(latest.get("price_normal"))
    append_current = (
        valid_price(current_offer) is not None
        and (latest_offer != valid_price(current_offer) or latest_normal != valid_price(current_normal))
    )
    if current_moment is not None and append_current:
        parsed.append(
            (
                current_moment,
                {
                    "price": current_offer,
                    "price_offer": current_offer,
                    "price_normal": current_normal,
                    "price_basis": "current",
                    "scraped_at": current_moment.isoformat(),
                },
            )
        )
    parsed.sort(key=lambda item: item[0])

    by_day: dict[date, dict[str, Any]] = {}
    for moment, entry in parsed:
        offer = valid_price(entry.get("price_offer"))
        if offer is None:
            offer = valid_price(entry.get("price"))
        normal = valid_price(entry.get("price_normal"))
        if offer is None and normal is None:
            continue
        day = santiago_day(moment)
        row = by_day.setdefault(
            day,
            {
                "day": day.isoformat(),
                "scraped_at": moment.isoformat(),
                "offer": None,
                "normal": None,
                "price_basis": entry.get("price_basis") or "published",
            },
        )
        row["scraped_at"] = moment.isoformat()
        row["price_basis"] = entry.get("price_basis") or row["price_basis"]
        if offer is not None:
            row["offer"] = offer
        # Un duplicado posterior sin precio normal no borra una referencia
        # válida observada ese mismo día.
        if normal is not None:
            row["normal"] = normal

    observations = [by_day[day] for day in sorted(by_day)]
    for row in observations:
        offer, normal = row["offer"], row["normal"]
        row["saving"] = normal - offer if offer is not None and normal is not None and offer < normal else 0
    return observations


def _within(rows: list[tuple[datetime | None, int]], days: int, now: datetime) -> list[int]:
    limit = now - timedelta(days=days)
    inside = [price for moment, price in rows if moment is not None and moment >= limit]
    return inside or [price for _, price in rows]


def _summary(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "max": None, "median": None}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "median": int(round(median(values))),
    }


def baseline_price(
    rows: list[tuple[datetime | None, int]],
    now: datetime,
    days: int = 90,
    recent_days: int = RECENT_DAYS,
) -> int | None:
    """Precio habitual, ignorando los últimos días para no contaminarlo con el alza reciente."""
    limit = now - timedelta(days=days)
    cutoff = now - timedelta(days=recent_days)
    older = [price for moment, price in rows if moment is not None and limit <= moment < cutoff]
    if len(older) < 2:
        older = [price for _, price in rows][:-1]
    if not older:
        return None
    return int(round(median(older)))


def fake_discount(
    rows: list[tuple[datetime | None, int]],
    current: int | None,
    previous: int | None,
    now: datetime,
) -> dict[str, Any] | None:
    """Detecta el 'descuento' que solo deshace un alza reciente."""
    if current is None or previous in (None, 0) or previous <= current:
        return None
    baseline = baseline_price(rows, now)
    if baseline is None:
        return None
    if previous <= baseline * (1 + INFLATION_MARGIN):
        return None
    if current < baseline * 0.98:
        return None
    return {
        "baseline": baseline,
        "inflated_from": previous,
        "over_baseline_percent": round((previous - baseline) * 100 / baseline, 1),
    }


def _changed_days_ago(
    rows: list[tuple[datetime | None, int]],
    current: int | None,
    now: datetime,
) -> int | None:
    """Hace cuántos días el precio quedó en su valor actual."""
    if current is None:
        return None
    moment = None
    for stamp, price in reversed(rows):
        if price != current:
            break
        moment = stamp
    if moment is None:
        return None
    return max(0, (now - moment).days)


MIN_TRACKED_DAYS = 14
NEAR_LOW_PERCENT = 10
# 3%: Easy/Paris a $399.990 vs $401.000 no es un precio menor de verdad.
MIN_CHEAPER_RATIO = 0.03
# Un peso de redondeo no cuenta como otro precio ni como descuento de vitrina.
PRICE_EQUAL_TOLERANCE = 1


def cheaper_before(
    points: list[dict[str, Any]] | None,
    current: int | None,
    *,
    min_ratio: float = MIN_CHEAPER_RATIO,
) -> dict[str, Any] | None:
    """Si este aviso ya se vendió más barato, el mínimo y el día más reciente."""
    if not current:
        return None
    better = [(moment, price) for moment, price in series(points) if price < current]
    if not better:
        return None
    low = min(price for _, price in better)
    gap = current - low
    if gap / current < min_ratio:
        return None
    stamped = [moment for moment, price in better if price == low and moment]
    on = max(stamped).date().isoformat() if stamped else None
    return {
        "price": low,
        "on": on,
        "gap": gap,
        "gap_percent": round(gap * 100 / current, 1),
    }


def cheaper_elsewhere(
    offer: dict[str, Any],
    peers: list[dict[str, Any]],
    *,
    min_ratio: float = MIN_CHEAPER_RATIO,
) -> dict[str, Any] | None:
    """Si otra tienda cobra menos el mismo producto, la más barata.

    Sodimac ≡ Falabella (misma cadena): no cuenta como «más barato en otra tienda».
    """
    from retail.compare import same_retailer

    price = _offer_price(offer)
    if not price:
        return None

    def available(peer: dict[str, Any]) -> bool:
        if peer.get("stale") is True or peer.get("available") is False:
            return False
        stock = peer.get("stock")
        if isinstance(stock, (int, float)) and stock <= 0:
            return False
        raw = peer.get("availability") or peer.get("stock_status") or peer.get("status") or ""
        if isinstance(raw, dict):
            raw = " ".join(str(value) for value in raw.values())
        text = str(raw).casefold()
        unavailable = (
            "sin stock", "agotado", "no disponible", "out of stock",
            "unavailable", "sold out",
        )
        return not any(label in text for label in unavailable)

    others = [
        peer
        for peer in peers
        if not same_retailer(peer.get("store"), offer.get("store"))
        and _offer_price(peer) is not None
        and available(peer)
    ]
    if not others:
        return None
    rival = min(others, key=lambda row: (_offer_price(row) or 10**15, row.get("store") or ""))
    rival_price = _offer_price(rival) or 0
    gap = price - rival_price
    if gap <= 0 or gap / price < min_ratio:
        return None
    return {
        "store": rival.get("store"),
        "store_title": rival.get("store_title") or rival.get("store"),
        "price": rival_price,
        "gap": gap,
        "gap_percent": round(gap * 100 / price, 1),
    }


def _offer_price(offer: dict[str, Any]) -> int | None:
    price = offer.get("price")
    if price in (None, 0):
        return None
    try:
        value = int(price)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _list_price(offer: dict[str, Any]) -> int | None:
    for key in ("price_normal", "price_internet"):
        raw = offer.get(key)
        if raw in (None, 0):
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def has_shelf_discount(offer: dict[str, Any]) -> bool:
    """True si la tienda publica un 'antes' o un % sobre el precio de venta."""
    price = _offer_price(offer)
    if price is None:
        return False
    listed = _list_price(offer)
    if listed is not None and listed > price + PRICE_EQUAL_TOLERANCE:
        return True
    try:
        declared = abs(int(offer.get("discount_percent") or 0))
    except (TypeError, ValueError):
        declared = 0
    return 0 < declared < 100


def prices_match_or_lower(peer_price: int, offer_price: int) -> bool:
    """El par es el mismo precio (1 peso) o más barato."""
    return peer_price <= offer_price + PRICE_EQUAL_TOLERANCE


def mark_false_list_discounts(groups: list[dict[str, Any]]) -> None:
    """Si otra tienda vende igual o más barato *sin* oferta, el %/ahorro de vitrina es aparente.

    Paris a $665.990 con −23% y Lider al mismo precio de lista: el descuento de
    Paris no es real. Si todas las tiendas muestran descuento por su cuenta, no
    se toca. No pisa el payload crudo: solo flags derivados en el aviso.
    Sodimac ≡ Falabella no cuenta como testigo de otra tienda.
    """
    from retail.compare import retailer_key, same_retailer

    for group in groups:
        offers = [item for item in (group.get("offers") or []) if _offer_price(item)]
        retailers = {
            retailer_key(item.get("store")) or item.get("store")
            for item in offers
            if item.get("store")
        }
        if not group.get("comparable") and len(retailers) < 2:
            continue
        if len(retailers) < 2:
            continue
        full_price = [item for item in offers if not has_shelf_discount(item)]
        if not full_price:
            continue
        for offer in offers:
            if not has_shelf_discount(offer):
                continue
            price = _offer_price(offer)
            if price is None:
                continue
            witness = next(
                (
                    peer
                    for peer in full_price
                    if not same_retailer(peer.get("store"), offer.get("store"))
                    and prices_match_or_lower(_offer_price(peer) or 0, price)
                ),
                None,
            )
            if witness is None:
                continue
            offer["fake_discount"] = True
            offer["precio_normal"] = True
            offer["false_discount_store"] = witness.get("store")


def _span_days(rows: list[tuple[datetime | None, int]], now: datetime) -> int:
    stamps = [moment for moment, _ in rows if moment is not None]
    return (now - min(stamps)).days if stamps else 0


def drop_events(rows: list[tuple[datetime | None, int]]) -> list[dict[str, Any]]:
    """Cada bajada real del historial: precio anterior, precio al que quedó y fecha.

    Es la misma regla que la columna «Bajas de precio»: solo hay baja si el
    punto siguiente es menor. Una subida o un precio igual no cuenta.
    """
    found: list[dict[str, Any]] = []
    for (_, before), (moment, after) in zip(rows, rows[1:]):
        if before > after > 0:
            found.append(
                {
                    "previous_price": before,
                    "price": after,
                    "at": moment,
                    "percent": round((before - after) * 100 / before, 1),
                }
            )
    return found


def classified_drop_events(rows: list[tuple[datetime | None, int]]) -> list[dict[str, Any]]:
    """Bajas con la evaluación de inflación correspondiente a cada evento."""
    found: list[dict[str, Any]] = []
    for index, ((_, before), (moment, after)) in enumerate(zip(rows, rows[1:]), start=1):
        if not (before > after > 0):
            continue
        found.append(
            {
                "previous_price": before,
                "price": after,
                "at": moment,
                "percent": round((before - after) * 100 / before, 1),
                "inflated": bool(
                    fake_discount(
                        rows[: index + 1],
                        after,
                        before,
                        moment or datetime.now(timezone.utc),
                    )
                ),
            }
        )
    return found


def drops(rows: list[tuple[datetime | None, int]]) -> list[tuple[datetime | None, float]]:
    """Cada bajada de precio observada, con su fecha y cuánto bajó en porcentaje."""
    return [(item["at"], item["percent"]) for item in drop_events(rows)]


def _cheaper_label(cheaper: dict[str, Any]) -> tuple[str, str]:
    """Nombre de tienda y precio formateado para copys de «más barato en»."""
    from retail.store_display import clean_store_display_name

    label = clean_store_display_name(
        cheaper.get("store_title") or cheaper.get("store") or "otra tienda"
    ) or "otra tienda"
    try:
        price = int(cheaper.get("price") or 0)
    except (TypeError, ValueError):
        price = 0
    money = f"${price:,}".replace(",", ".") if price > 0 else ""
    return label, money


def apply_cheaper_elsewhere_gate(
    *,
    stats: dict[str, Any] | None = None,
    timing: dict[str, Any] | None = None,
    cheaper: dict[str, Any] | None = None,
) -> None:
    """Si otra tienda comparable es más barata, no recomendar comprar ni afirmar mínimo global.

    El historial propio puede seguir siendo el mínimo de *esa* tienda; la UI no debe
    decir CONVIENE COMPRAR / «precio más bajo que le hemos visto» mientras exista
    un «Más barato en X».
    """
    if not cheaper:
        return
    try:
        rival = int(cheaper.get("price") or 0)
    except (TypeError, ValueError):
        rival = 0
    if rival <= 0:
        return

    label, money = _cheaper_label(cheaper)
    elsewhere = f"{label}" + (f" · {money}" if money else "")

    if timing is not None and timing.get("advice") == "comprar":
        timing["advice"] = "esperar"
        timing["reason"] = f"Hay un precio más bajo en {elsewhere}."
        timing["blocked_by_cheaper_elsewhere"] = True

    if stats is None:
        return

    store_lowest = bool(stats.get("is_lowest_ever"))
    if store_lowest:
        stats["is_lowest_at_store"] = True
        stats["is_lowest_ever"] = False

    verdict = str(stats.get("verdict") or "")
    if store_lowest or "más bajo que le hemos visto" in verdict:
        percent = stats.get("percent_vs_median")
        if percent is not None and percent <= -10:
            stats["level"] = "good"
            stats["verdict"] = (
                f"Bajo lo habitual en esta tienda, pero hay menos en {elsewhere}."
            )
        elif percent is not None and percent <= -2:
            stats["level"] = "good"
            stats["verdict"] = (
                f"Un poco bajo lo habitual aquí; hay menos en {elsewhere}."
            )
        else:
            stats["level"] = "normal"
            stats["verdict"] = (
                f"Mínimo en el historial de esta tienda, pero hay menos en {elsewhere}."
            )


def buy_or_wait(
    points: list[dict[str, Any]] | None,
    current: int | None = None,
    now: datetime | None = None,
    *,
    cheaper_elsewhere: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """¿Conviene comprar hoy o suele bajar más?

    Responde con el patrón del propio producto: cada cuánto baja, cuánto baja y
    dónde queda el precio de hoy dentro de todo lo que le hemos visto. Mientras
    no haya historial suficiente lo dice en vez de inventar un veredicto, y
    avisa cuántos días faltan para poder responder.

    Si ``cheaper_elsewhere`` trae una oferta comparable más barata en otra tienda,
    no recomienda comprar aunque el historial propio esté en su mínimo.
    """
    now = now or datetime.now(timezone.utc)
    rows = series(points)
    prices = [price for _, price in rows]
    if current is None and prices:
        current = prices[-1]
    tracked = _span_days(rows, now)
    bajadas = drops(rows)

    answer: dict[str, Any] = {
        "ready": False,
        "advice": "sin_datos",
        "days_tracked": tracked,
        "drops": len(bajadas),
        "typical_drop_percent": None,
        "days_since_last_drop": None,
        "typical_days_between_drops": None,
        "position_percent": None,
        "reason": "",
    }

    if current is None or len(prices) < 2 or tracked < MIN_TRACKED_DAYS:
        faltan = max(0, MIN_TRACKED_DAYS - tracked)
        answer["missing_days"] = faltan
        answer["reason"] = (
            f"Llevamos {tracked} {'día' if tracked == 1 else 'días'} siguiendo este precio. "
            f"En {faltan} más se puede decir si conviene esperar."
        )
        return answer

    low, high = min(prices), max(prices)
    answer["ready"] = True
    answer["position_percent"] = 0 if high == low else round((current - low) * 100 / (high - low))
    if bajadas:
        answer["typical_drop_percent"] = round(median([percent for _, percent in bajadas]), 1)
        fechas = [moment for moment, _ in bajadas if moment is not None]
        if fechas:
            answer["days_since_last_drop"] = (now - max(fechas)).days
        if len(fechas) >= 2:
            entre = [(later - earlier).days for earlier, later in zip(fechas, fechas[1:])]
            answer["typical_days_between_drops"] = int(round(median(entre)))

    cerca_del_minimo = low > 0 and (current - low) * 100 / low <= NEAR_LOW_PERCENT
    cadencia = answer["typical_days_between_drops"]
    desde_la_ultima = answer["days_since_last_drop"]

    if cerca_del_minimo:
        answer["advice"] = "comprar"
        answer["reason"] = (
            "Está en lo más bajo que le hemos visto."
            if current <= low
            else f"Está a un {round((current - low) * 100 / low)}% de su mínimo histórico."
        )
    else:
        # Regla adicional: si el precio es el mínimo en los últimos 6 meses, comprar.
        six_months_ago = now - timedelta(days=30 * 6)
        recent_low = None
        for moment, price in rows:
            if moment is None:
                continue
            if moment >= six_months_ago:
                if recent_low is None or price < recent_low:
                    recent_low = price
        if current is not None and recent_low is not None and current <= recent_low:
            answer["advice"] = "comprar"
            answer["reason"] = "Precio en o por debajo del mínimo observado en los últimos 6 meses."
        elif cadencia and desde_la_ultima is not None and desde_la_ultima < cadencia:
            answer["advice"] = "esperar"
            answer["reason"] = (
                f"Suele bajar cada {cadencia} días y la última fue hace {desde_la_ultima}: "
                f"cuando baja lo hace un {answer['typical_drop_percent']}%."
            )
        elif answer["position_percent"] is not None and answer["position_percent"] >= 60:
            answer["advice"] = "esperar"
            answer["reason"] = f"Hoy está caro para lo que suele costar: llegó a ${low:,}.".replace(",", ".")
        else:
            answer["advice"] = "indeciso"
            answer["reason"] = "Está en un precio corriente, ni de los buenos ni de los malos."

    apply_cheaper_elsewhere_gate(timing=answer, cheaper=cheaper_elsewhere)
    return answer


def price_stats(
    points: list[dict[str, Any]] | None,
    current: int | None = None,
    now: datetime | None = None,
    *,
    cheaper_elsewhere: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    rows = series(points)
    prices = [price for _, price in rows]
    if current is None and prices:
        current = prices[-1]

    previous = None
    for price in reversed(prices[:-1] if prices and prices[-1] == current else prices):
        if price != current:
            previous = price
            break

    stats: dict[str, Any] = {
        "current": current,
        "previous": previous,
        "points": len(prices),
        "windows": {str(days): _summary(_within(rows, days, now)) for days in WINDOWS},
        "all": _summary(prices),
        "changed_days_ago": _changed_days_ago(rows, current, now),
    }
    reference = stats["windows"][str(WINDOWS[-1])]
    stats["median"] = reference["median"]
    stats["min"] = reference["min"]
    stats["max"] = reference["max"]
    stats["fake_discount"] = fake_discount(rows, current, previous, now)
    stats["is_lowest_ever"] = bool(prices) and current is not None and current <= min(prices) and len(prices) >= 3
    stats["is_lowest_at_store"] = bool(stats["is_lowest_ever"])

    median_value = reference["median"]
    if current is None or not median_value:
        stats["percent_vs_median"] = None
        stats["level"] = "unknown"
        stats["verdict"] = "Sin historial suficiente para comparar."
        apply_cheaper_elsewhere_gate(stats=stats, cheaper=cheaper_elsewhere)
        return stats

    percent = round((current - median_value) * 100 / median_value, 1)
    stats["percent_vs_median"] = percent

    if stats["fake_discount"]:
        level = "fake"
        verdict = (
            f"Ojo: la baja solo deshace un alza reciente, el precio habitual era "
            f"${median_value:,}".replace(",", ".")
        )
    elif stats["is_lowest_ever"]:
        level = "great"
        verdict = "Es el precio más bajo que le hemos visto."
    elif percent <= -10:
        level = "great"
        verdict = f"Está {abs(percent):.0f}% bajo su precio habitual."
    elif percent <= -2:
        level = "good"
        verdict = f"Un poco bajo lo habitual ({abs(percent):.0f}%)."
    elif percent >= 5:
        level = "high"
        verdict = f"Está {percent:.0f}% sobre su precio habitual, conviene esperar."
    else:
        level = "normal"
        verdict = "Precio parecido al habitual."

    stats["level"] = level
    stats["verdict"] = verdict
    apply_cheaper_elsewhere_gate(stats=stats, cheaper=cheaper_elsewhere)
    return stats
