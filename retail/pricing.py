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
    """Si otra tienda cobra menos el mismo producto, la más barata."""
    price = offer.get("price")
    if not price:
        return None
    others = [
        peer
        for peer in peers
        if peer.get("store") != offer.get("store") and peer.get("price") not in (None, 0)
    ]
    if not others:
        return None
    rival = min(others, key=lambda row: (row["price"], row.get("store") or ""))
    rival_price = int(rival["price"])
    gap = int(price) - rival_price
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
    """
    for group in groups:
        offers = [item for item in (group.get("offers") or []) if _offer_price(item)]
        stores = {item.get("store") for item in offers if item.get("store")}
        if not group.get("comparable") and len(stores) < 2:
            continue
        if len(stores) < 2:
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
                    if peer.get("store") != offer.get("store")
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


def buy_or_wait(
    points: list[dict[str, Any]] | None,
    current: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """¿Conviene comprar hoy o suele bajar más?

    Responde con el patrón del propio producto: cada cuánto baja, cuánto baja y
    dónde queda el precio de hoy dentro de todo lo que le hemos visto. Mientras
    no haya historial suficiente lo dice en vez de inventar un veredicto, y
    avisa cuántos días faltan para poder responder.
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
        rows = series(points)
        recent_low = None
        for moment, price in rows:
            if moment is None:
                continue
            if moment >= six_months_ago:
                if recent_low is None or price < recent_low:
                    recent_low = price
        try:
            if current is not None and recent_low is not None and current <= recent_low:
                answer["advice"] = "comprar"
                answer["reason"] = "Precio en o por debajo del mínimo observado en los últimos 6 meses."
                return answer
        except Exception:
            pass
    # Continuar evaluaciones después de la regla de 6 meses
    if cadencia and desde_la_ultima is not None and desde_la_ultima < cadencia:
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
    return answer


def price_stats(
    points: list[dict[str, Any]] | None,
    current: int | None = None,
    now: datetime | None = None,
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

    median_value = reference["median"]
    if current is None or not median_value:
        stats["percent_vs_median"] = None
        stats["level"] = "unknown"
        stats["verdict"] = "Sin historial suficiente para comparar."
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
    return stats
