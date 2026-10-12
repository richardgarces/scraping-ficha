"""Robots-aware audits of offers currently published in ``/api/reales``."""

from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import httpx

from retail.http import DEFAULT_HEADERS
from retail.models import Target
from retail.real_offer_worker import chile_day
from retail.registry import get_client, list_stores
from retail.reales import EXCLUDED_REAL_OFFER_STORES

logger = logging.getLogger(__name__)

MAX_SAMPLE_SIZE = 100
DEFAULT_REQUEST_DELAY = 1.0
MAX_REDIRECTS = 5
REPORT_DIRECTORY = Path("reports/offer-verification")
USER_AGENT = "PreciosAuditoria/1.0 (+https://precios.meincart.cl/)"
CHILE = ZoneInfo("America/Santiago")
ROBOTS_CACHE_TTL = 3600.0
_ROBOTS_CACHE: dict[str, tuple[RobotFileParser, float, float]] = {}
_ROBOTS_CACHE_LOCK = threading.Lock()
_REQUEST_SCHEDULE: dict[str, float] = {}
_REQUEST_SCHEDULE_LOCK = threading.Lock()

_PRICE_FIELDS = (
    "price_all_payment",
    "price_normal",
    "price_card",
    "price_coupon",
)
_TEXT_FIELDS = ("payment_conditions", "coupon_code")
_OBSERVED_FIELDS = (
    *_PRICE_FIELDS,
    "stock",
    "availability",
    *_TEXT_FIELDS,
    "shipping_cost",
    "shipping_free_threshold",
    "shipping_region",
)


class RobotsDenied(RuntimeError):
    def __init__(self, reason: str, *, url: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.url = url


class RobotsAwareSession:
    """HTTP adapter enforcing store-host allowlists, robots rules and crawl delay."""

    def __init__(
        self,
        *,
        store: str,
        allowed_hosts: set[str],
        timeout: float = 12.0,
    ) -> None:
        self.store = store
        self.allowed_hosts = {host.lower().strip(".") for host in allowed_hosts if host}
        self.timeout = timeout
        self.headers = {**DEFAULT_HEADERS, "User-Agent": USER_AGENT}
        self._client = httpx.Client(
            headers=self.headers,
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        )
        self._robots: dict[str, tuple[RobotFileParser, float]] = {}
        self.last_url = ""
        self.last_status: int | None = None
        self.last_content_type = ""

    def _origin(self, url: str) -> tuple[str, str]:
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise RobotsDenied("invalid_product_url", url=url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise RobotsDenied("invalid_product_url", url=url) from exc
        default_port = 443 if parsed.scheme.lower() == "https" else 80
        if parsed.username or parsed.password or port not in {None, default_port}:
            raise RobotsDenied("invalid_product_url", url=url)
        host = parsed.hostname.lower().strip(".")
        if not any(host == allowed or host.endswith(f".{allowed}") for allowed in self.allowed_hosts):
            raise RobotsDenied("host_not_allowed", url=url)
        return f"{parsed.scheme.lower()}://{host}", host

    def _robots_rules(self, origin: str) -> tuple[RobotFileParser, float]:
        cached = self._robots.get(origin)
        if cached:
            return cached
        with _ROBOTS_CACHE_LOCK:
            shared = _ROBOTS_CACHE.get(origin)
            if shared and shared[2] > time.monotonic():
                result = (shared[0], shared[1])
                self._robots[origin] = result
                return result
        robots_url = f"{origin}/robots.txt"
        try:
            response = self._client.get(robots_url)
        except httpx.HTTPError as exc:
            raise RobotsDenied(f"robots_unavailable:{type(exc).__name__}", url=robots_url) from exc
        if 300 <= response.status_code < 400:
            raise RobotsDenied("robots_redirect_not_followed", url=robots_url)
        if response.status_code == 404:
            lines = ["User-agent: *"]
        elif 200 <= response.status_code < 300:
            lines = response.text.splitlines()
        else:
            raise RobotsDenied(f"robots_http_{response.status_code}", url=robots_url)
        parser = RobotFileParser(robots_url)
        parser.parse(lines)
        delay = parser.crawl_delay(USER_AGENT) or parser.crawl_delay("*") or 0.0
        request_rate = parser.request_rate(USER_AGENT) or parser.request_rate("*")
        if request_rate and request_rate.requests > 0:
            delay = max(delay, request_rate.seconds / request_rate.requests)
        result = (parser, max(DEFAULT_REQUEST_DELAY, float(delay)))
        self._robots[origin] = result
        with _ROBOTS_CACHE_LOCK:
            _ROBOTS_CACHE[origin] = (*result, time.monotonic() + ROBOTS_CACHE_TTL)
        return result

    def _authorize_and_wait(self, url: str) -> tuple[str, str]:
        origin, host = self._origin(url)
        rules, delay = self._robots_rules(origin)
        if not rules.can_fetch(USER_AGENT, url):
            raise RobotsDenied("robots_disallowed", url=url)
        now = time.monotonic()
        with _REQUEST_SCHEDULE_LOCK:
            rate_key = self.store or host
            next_allowed = _REQUEST_SCHEDULE.get(rate_key, now)
            wait = max(0.0, next_allowed - now)
            _REQUEST_SCHEDULE[rate_key] = max(now, next_allowed) + delay
        if wait:
            time.sleep(wait)
        return origin, host

    def _send(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, str, str]:
        current = url
        current_method = method
        current_params = params
        current_json = json_body
        for redirect_count in range(MAX_REDIRECTS + 1):
            self._authorize_and_wait(current)
            try:
                response = self._client.request(
                    current_method,
                    current,
                    params=current_params or {},
                    json=current_json,
                    follow_redirects=False,
                )
            except httpx.HTTPError:
                raise
            self.last_url = str(response.url)
            self.last_status = response.status_code
            self.last_content_type = response.headers.get("content-type", "")
            location = response.headers.get("location")
            if response.status_code not in {301, 302, 303, 307, 308} or not location:
                return response.status_code, self.last_content_type, response.text
            if redirect_count >= MAX_REDIRECTS:
                raise RobotsDenied("too_many_redirects", url=current)
            target = urljoin(str(response.url), location)
            self._origin(target)
            current = target
            current_params = None
            if response.status_code == 303 or (
                response.status_code in {301, 302} and current_method != "GET"
            ):
                current_method = "GET"
                current_json = None
        raise RobotsDenied("too_many_redirects", url=current)

    def get(self, url: str, params: dict[str, Any] | None = None) -> tuple[int, str, str]:
        return self._send("GET", url, params=params)

    def post(
        self,
        url: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> tuple[int, str, str]:
        return self._send("POST", url, params=params, json_body=json_body)

    def close(self) -> None:
        self._client.close()


def _allowed_hosts(site: str) -> set[str]:
    host = (urlsplit(site if "://" in site else f"https://{site}").hostname or "").lower()
    return {host.removeprefix("www.")} if host else set()


def _as_product_dict(product: Any) -> dict[str, Any]:
    if isinstance(product, dict):
        return product
    to_dict = getattr(product, "to_dict", None)
    if callable(to_dict):
        return to_dict(flatten_specs=False)
    return {}


def _selected_scraped_product(products: list[Any], expected: dict[str, Any]) -> dict[str, Any] | None:
    expected_id = str(expected.get("product_id") or "").strip()
    for product in products:
        row = _as_product_dict(product)
        if expected_id and expected_id in {
            str(row.get("product_id") or "").strip(),
            str(row.get("sku_id") or "").strip(),
        }:
            return row
    return None


def _norm_text(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _comparison(expected: Any, observed: Any) -> dict[str, Any]:
    if expected is None or observed is None:
        return {"status": "not_verified", "expected": expected, "observed": observed}
    result: dict[str, Any] = {
        "status": "verified",
        "expected": expected,
        "observed": observed,
        "discrepancy": False,
    }
    if isinstance(expected, bool) or isinstance(observed, bool):
        result["discrepancy"] = expected != observed
        return result
    if isinstance(expected, (int, float)) and isinstance(observed, (int, float)):
        absolute = abs(float(observed) - float(expected))
        result["absolute_difference"] = absolute
        result["relative_difference_percent"] = (
            absolute / abs(float(expected)) * 100 if float(expected) else None
        )
        result["discrepancy"] = absolute != 0
    else:
        result["discrepancy"] = _norm_text(expected) != _norm_text(observed)
    return result


def _expected_snapshot(product: dict[str, Any]) -> dict[str, Any]:
    return {
        "price_all_payment": product.get("price_all_payment") or product.get("price_internet"),
        "price_normal": product.get("price_normal"),
        "price_card": product.get("price_card") or product.get("price_cmr"),
        "price_coupon": product.get("price_coupon"),
        "payment_conditions": product.get("payment_conditions"),
        "coupon_code": product.get("coupon_code"),
        "stock": product.get("stock") if product.get("stock_verified") else None,
        "availability": product.get("availability"),
        "shipping_cost": product.get("shipping_cost"),
        "shipping_free_threshold": product.get("shipping_free_threshold"),
        "shipping_region": product.get("shipping_region"),
        "stock_verified": bool(product.get("stock_verified")),
        "shipping_source": product.get("shipping_source"),
    }


def _observed_snapshot(scraped: dict[str, Any]) -> dict[str, Any]:
    return {
        "price_all_payment": scraped.get("price_all_payment") or scraped.get("price_internet"),
        "price_normal": scraped.get("price_normal"),
        "price_card": scraped.get("price_card") or scraped.get("price_cmr"),
        "price_coupon": scraped.get("price_coupon"),
        "payment_conditions": scraped.get("payment_conditions"),
        "coupon_code": scraped.get("coupon_code"),
        "stock": scraped.get("stock"),
        "availability": scraped.get("availability"),
        "shipping_cost": scraped.get("shipping_cost"),
        "shipping_free_threshold": scraped.get("shipping_free_threshold"),
        "shipping_region": scraped.get("shipping_region"),
        "stock_verified": bool(scraped.get("stock_verified")),
        "shipping_source": scraped.get("shipping_source"),
    }


def _differences(expected: dict[str, Any], observed: dict[str, Any] | None) -> dict[str, Any]:
    actual = observed or {}
    changes = {}
    for field in _OBSERVED_FIELDS:
        left = expected.get(field)
        right = actual.get(field)
        comparison = _comparison(left, right)
        if field == "stock" and not expected.get("stock_verified"):
            comparison = {"status": "not_verified", "expected": None, "observed": right}
        if field == "stock" and not actual.get("stock_verified"):
            comparison = {"status": "not_verified", "expected": left, "observed": right}
        if field in {"shipping_cost", "shipping_free_threshold"}:
            old_region = _norm_text(expected.get("shipping_region"))
            new_region = _norm_text(actual.get("shipping_region"))
            if old_region and new_region and old_region != new_region:
                comparison = {
                    "status": "not_comparable",
                    "expected": left,
                    "observed": right,
                    "reason": "shipping_region_differs",
                }
        changes[field] = comparison
    return changes


def verify_offer(
    offer: dict[str, Any],
    product: dict[str, Any],
    *,
    spec: Any,
    policy_session_factory=RobotsAwareSession,
) -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc)
    store = str(product.get("store") or offer.get("store") or "").strip().lower()
    expected = _expected_snapshot(product)
    result: dict[str, Any] = {
        "store": store,
        "product_id": str(product.get("product_id") or ""),
        "name": product.get("name") or offer.get("name") or "",
        "url": str(product.get("url") or offer.get("url") or ""),
        "checked_at": checked_at,
        "expected": expected,
        "observed": {},
        "differences": {},
        "url_status": "not_verified",
        "url_response_status": None,
        "verification_status": "not_verified",
    }
    allowed_hosts = _allowed_hosts(str(getattr(spec, "site", "") or ""))
    session = policy_session_factory(
        store=store,
        allowed_hosts=allowed_hosts,
        timeout=12.0,
    )
    try:
        status, _content_type, _body = session.get(result["url"])
        result["url_response_status"] = status
        result["final_url"] = session.last_url or result["url"]
        if status < 200 or status >= 400:
            result["url_status"] = "broken"
            result["verification_error"] = f"http_{status}"
            result["differences"] = _differences(expected, None)
            return result

        result["url_status"] = "functional"
        client = get_client(store, delay=0, timeout=12, retries=0)
        client.http = session

        def open_robots_session(headers: dict[str, str] | None = None):
            if headers:
                safe_headers = {key: value for key, value in headers.items() if key.lower() != "user-agent"}
                session.headers.update(safe_headers)
                session._client.headers.update(safe_headers)
            session.headers["User-Agent"] = USER_AGENT
            session._client.headers["User-Agent"] = USER_AGENT
            client.http = session
            return session

        client.open_http = open_robots_session
        try:
            from retail.product_refresh import _destination_refresh_target

            raw_product_id = str(product.get("product_id") or "")
            scrape_id = raw_product_id
            target_store = store
            destination = _destination_refresh_target(store, raw_product_id, product)
            if destination:
                target_store, scrape_id = destination
            if target_store != store:
                raise RobotsDenied("aggregator_target_not_a_store_page", url=result["url"])
            scraped_products = client.scrape(
                Target(kind="product", product_id=scrape_id, raw_url=result["url"]),
                max_pages=1,
                max_items=1,
                detalle=True,
            )
            scraped = _selected_scraped_product(scraped_products or [], product)
        finally:
            client.close()
        if scraped is None:
            result["verification_error"] = "store_parser_returned_no_matching_product"
            result["differences"] = _differences(expected, None)
            return result
        observed = _observed_snapshot(scraped)
        result["observed"] = observed
        result["differences"] = _differences(expected, observed)
        verified_fields = sum(
            item.get("status") == "verified"
            for item in result["differences"].values()
        )
        result["verification_status"] = "verified" if verified_fields else "not_verified"
        result["parser_updated_at"] = scraped.get("scraped_at")
        return result
    except RobotsDenied as exc:
        result["verification_error"] = exc.reason
        result["blocked_url"] = exc.url
        result["differences"] = _differences(expected, None)
        return result
    except httpx.HTTPError as exc:
        if result["url_status"] == "not_verified":
            result["url_status"] = "broken"
        result["verification_error"] = f"{type(exc).__name__}: {str(exc)}"[:300]
        result["differences"] = _differences(expected, None)
        return result
    except (ValueError, LookupError) as exc:
        result["verification_error"] = f"{type(exc).__name__}: {str(exc)}"[:300]
        result["differences"] = _differences(expected, None)
        return result
    except Exception as exc:
        logger.exception("Fallo al verificar oferta %s/%s", store, result["product_id"])
        result["verification_error"] = f"{type(exc).__name__}: {str(exc)}"[:300]
        result["differences"] = _differences(expected, None)
        return result
    finally:
        session.close()


def _sample_public_offers(repo: Any, sample_size: int) -> tuple[int, list[dict[str, Any]]]:
    day = chile_day()
    pipeline = [
        {"$match": {"day": day, "is_real": True}},
        {
            "$lookup": {
                "from": repo.collection.name,
                "localField": "product_id",
                "foreignField": "_id",
                "as": "product",
            }
        },
        {"$set": {"product": {"$first": "$product"}}},
        {
            "$match": {
                "product": {"$ne": None},
                "analysis.kinds": {"$in": ["comparacion", "historial"]},
                "product.store": {"$nin": sorted(EXCLUDED_REAL_OFFER_STORES)},
                "$expr": {"$eq": ["$evaluated_price", "$product.price"]},
            }
        },
        {
            "$facet": {
                "count": [{"$count": "total"}],
                "sample": [
                    {"$sample": {"size": sample_size}},
                    {
                        "$project": {
                            "evaluated_price": 1,
                            "product._id": 1,
                            "product.store": 1,
                            "product.product_id": 1,
                            "product.name": 1,
                            "product.url": 1,
                            "product.price": 1,
                            "product.price_normal": 1,
                            "product.price_all_payment": 1,
                            "product.price_internet": 1,
                            "product.price_card": 1,
                            "product.price_cmr": 1,
                            "product.price_coupon": 1,
                            "product.coupon_code": 1,
                            "product.payment_conditions": 1,
                            "product.payment_card_name": 1,
                            "product.shipping_cost": 1,
                            "product.shipping_free_threshold": 1,
                            "product.shipping_region": 1,
                            "product.shipping_source": 1,
                            "product.stock": 1,
                            "product.stock_verified": 1,
                            "product.availability": 1,
                            "product.updated_at": 1,
                        }
                    },
                ],
            }
        },
    ]
    result = next(iter(repo.daily_real_offers.aggregate(pipeline)), {})
    count = int((result.get("count") or [{}])[0].get("total") or 0)
    return count, [
        {**(row.get("product") or {}), "evaluated_price": row.get("evaluated_price")}
        for row in result.get("sample") or []
    ]


def summarize_checks(checks: list[dict[str, Any]]) -> dict[str, Any]:
    url_attempts = [row for row in checks if row.get("url_status") in {"functional", "broken"}]
    functional = sum(row.get("url_status") == "functional" for row in url_attempts)
    comparable_prices = [
        row for row in checks
        if row.get("differences", {}).get("price_all_payment", {}).get("status") == "verified"
    ]
    discrepant_prices = [
        row for row in comparable_prices
        if row["differences"]["price_all_payment"].get("discrepancy")
    ]
    numeric_discrepancies = [
        row["differences"]["price_all_payment"]
        for row in discrepant_prices
        if "absolute_difference" in row["differences"]["price_all_payment"]
    ]
    absolute_deltas = [float(item["absolute_difference"]) for item in numeric_discrepancies]
    relative_deltas = [
        item["relative_difference_percent"]
        for item in numeric_discrepancies
        if item.get("relative_difference_percent") is not None
    ]
    fields = {}
    for field in _OBSERVED_FIELDS:
        comparisons = [row.get("differences", {}).get(field, {}) for row in checks]
        comparable = [item for item in comparisons if item.get("status") == "verified"]
        discrepant = sum(item.get("discrepancy", False) for item in comparable)
        fields[field] = {
            "comparable_count": len(comparable),
            "discrepancy_count": discrepant,
            "discrepancy_percent": discrepant / len(comparable) * 100 if comparable else None,
            "not_verified_count": sum(
                item.get("status") in {None, "not_verified"} for item in comparisons
            ),
            "not_comparable_count": sum(
                item.get("status") == "not_comparable" for item in comparisons
            ),
        }
    return {
        "sample_size": len(checks),
        "url_functional_count": functional,
        "url_attempted_count": len(url_attempts),
        "url_functional_percent": functional / len(url_attempts) * 100 if url_attempts else None,
        "url_not_verified_count": sum(row.get("url_status") == "not_verified" for row in checks),
        "price_comparable_count": len(comparable_prices),
        "price_discrepancy_count": len(discrepant_prices),
        "price_discrepancy_percent": (
            len(discrepant_prices) / len(comparable_prices) * 100 if comparable_prices else None
        ),
        "mean_absolute_price_difference": (
            sum(absolute_deltas) / len(absolute_deltas) if absolute_deltas else None
        ),
        "mean_relative_price_difference_percent": (
            sum(relative_deltas) / len(relative_deltas) if relative_deltas else None
        ),
        "price_difference_count": len(absolute_deltas),
        "relative_price_difference_count": len(relative_deltas),
        "fields": fields,
    }


def _previous_week_run(repo: Any, started_at: datetime) -> dict[str, Any] | None:
    return repo.offer_verification_runs.find_one(
        {
            "status": "completed",
            "started_at": {"$lte": started_at - timedelta(days=6)},
        },
        sort=[("started_at", -1)],
    )


def _markdown_report(
    run: dict[str, Any],
    checks: list[dict[str, Any]],
    metrics: dict[str, Any],
    previous: dict[str, Any] | None,
) -> str:
    def chile_timestamp(value: Any) -> str:
        if not isinstance(value, datetime):
            return str(value or "No disponible")
        utc_value = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return utc_value.astimezone(CHILE).isoformat(timespec="seconds")

    stamp = chile_timestamp(run["started_at"])

    def percent(value: Any) -> str:
        return "No verificado" if value is None else f"{float(value):.1f}%"

    def money(value: Any) -> str:
        return "No verificado" if value is None else f"${float(value):,.0f}".replace(",", ".")

    def table_cell(value: Any) -> str:
        return str(value or "—").replace("|", "\\|").replace("\r", " ").replace("\n", " ")

    lines = [
        "# Auditoría semanal de ofertas publicadas",
        "",
        f"- Corrida: `{run['id']}`",
        f"- Verificación: {stamp}",
        f"- Ofertas publicadas candidatas: {run['candidate_count']}",
        f"- Muestra revisada: {metrics['sample_size']} (máximo {MAX_SAMPLE_SIZE})",
        "",
        "## Resultados",
        "",
        "| Métrica | Resultado | Base |",
        "|---|---:|---:|",
        f"| Enlaces funcionales | {percent(metrics['url_functional_percent'])} | {metrics['url_functional_count']}/{metrics['url_attempted_count']} intentos; {metrics['url_not_verified_count']} no verificados |",
        f"| Discrepancia de precio sin tarjeta | {percent(metrics['price_discrepancy_percent'])} | {metrics['price_discrepancy_count']}/{metrics['price_comparable_count']} precios comparables |",
        f"| Diferencia absoluta media | {money(metrics['mean_absolute_price_difference'])} | n={metrics['price_difference_count']} |",
        f"| Diferencia relativa media | {percent(metrics['mean_relative_price_difference_percent'])} | n={metrics['relative_price_difference_count']} |",
        "",
        "### Cobertura de campos y discrepancias",
        "",
        "| Campo | Comparables | Discrepancias | No verificados | No comparables |",
        "|---|---:|---:|---:|---:|",
    ]
    for field in _OBSERVED_FIELDS:
        values = metrics["fields"][field]
        lines.append(
            f"| {field} | {values['comparable_count']} | "
            f"{values['discrepancy_count']} ({percent(values['discrepancy_percent'])}) | "
            f"{values['not_verified_count']} | {values['not_comparable_count']} |"
        )
    lines.extend([
        "",
        "Los precios con tarjeta/cupón, precio normal y despacho se comparan por separado en cada verificación. Cuando robots.txt bloquea una página, el sitio no responde o el scraper no puede verificar un campo, se registra **No verificado** y ese campo no entra en el denominador correspondiente.",
        "",
    ])
    if previous:
        old = previous.get("metrics") or {}
        lines.extend([
            "## Comparación semanal",
            "",
            f"Comparada con `{previous.get('_id')}` de "
            f"{chile_timestamp(previous.get('started_at'))}.",
            "",
            "| Métrica | Esta corrida | Corrida anterior | Diferencia |",
            "|---|---:|---:|---:|",
        ])
        for key, label in (
            ("url_functional_percent", "Enlaces funcionales"),
            ("price_discrepancy_percent", "Discrepancia de precio"),
            ("mean_absolute_price_difference", "Diferencia absoluta media (CLP)"),
            ("mean_relative_price_difference_percent", "Diferencia relativa media"),
        ):
            current = metrics.get(key)
            old_value = old.get(key)
            if current is None or old_value is None:
                delta = "No comparable"
            elif key == "mean_absolute_price_difference":
                delta = money(float(current) - float(old_value))
            else:
                delta = f"{float(current) - float(old_value):+.1f} pp"
            format_value = money if key == "mean_absolute_price_difference" else percent
            lines.append(
                f"| {label} | {format_value(current)} | "
                f"{format_value(old_value)} | {delta} |"
            )
        lines.append("")
    else:
        lines.extend([
            "## Comparación semanal",
            "",
            "No hay una corrida completada de al menos seis días de antigüedad para comparar.",
            "",
        ])
    discrepancy_rows = [
        row for row in checks
        if row.get("differences", {}).get("price_all_payment", {}).get("discrepancy")
    ]
    lines.extend([
        "## Ofertas con diferencia de precio",
        "",
        "| Tienda | Producto | Precio guardado sin tarjeta | Precio observado sin tarjeta | Fecha de comprobación |",
        "|---|---|---:|---:|---|",
    ])
    for row in discrepancy_rows:
        diff = row["differences"]["price_all_payment"]
        lines.append(
            f"| {table_cell(row.get('store'))} | {table_cell(row.get('name'))} | "
            f"{money(diff.get('expected'))} | {money(diff.get('observed'))} | "
            f"{chile_timestamp(row.get('checked_at'))} |"
        )
    if not discrepancy_rows:
        lines.append("| — | No se detectaron diferencias comparables | — | — | — |")
    lines.append("")
    return "\n".join(lines)


def run_offer_verification(
    repo: Any,
    *,
    sample_size: int = MAX_SAMPLE_SIZE,
    report_directory: str | Path = REPORT_DIRECTORY,
) -> dict[str, Any]:
    requested = max(1, min(MAX_SAMPLE_SIZE, int(sample_size)))
    started = datetime.now(timezone.utc)
    run_id = repo.offer_verification_runs.insert_one({
        "started_at": started,
        "status": "running",
        "requested_sample_size": requested,
        "selection_method": "uniform_random_from_current_public_real_offers",
        "source_day": chile_day(),
    }).inserted_id
    run = {"id": str(run_id), "started_at": started}
    try:
        candidate_count, offers = _sample_public_offers(repo, requested)
        if candidate_count == 0:
            raise RuntimeError("No hay ofertas publicadas vigentes para verificar.")
        specs = {spec.id: spec for spec in list_stores()}
        checks = []
        for offer in offers:
            store = str(offer.get("store") or "").strip().lower()
            product_id = str(offer.get("product_id") or "").strip()
            if not store or store not in specs or not product_id:
                checks.append({
                    "store": store,
                    "product_id": product_id,
                    "checked_at": datetime.now(timezone.utc),
                    "url_status": "not_verified",
                    "verification_status": "not_verified",
                    "verification_error": "missing_store_or_product_id",
                    "expected": _expected_snapshot(offer),
                    "observed": {},
                    "differences": _differences(_expected_snapshot(offer), None),
                })
                continue
            product = repo.product_detail(store, product_id)
            if product is None:
                product = offer
            check = verify_offer(offer, product, spec=specs[store])
            check["run_id"] = run_id
            check["source_product_id"] = product_id
            check["product_id"] = f"{store}:{product_id}"
            checks.append(check)
        if checks:
            repo.offer_verification_checks.insert_many(checks, ordered=False)
        metrics = summarize_checks(checks)
        previous = _previous_week_run(repo, started)
        report_run = {
            **run,
            "candidate_count": candidate_count,
            "metrics": metrics,
        }
        report = _markdown_report(report_run, checks, metrics, previous)
        report_path = Path(report_directory) / f"offer-verification-{run_id}.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
        ended = datetime.now(timezone.utc)
        run_update = {
            "status": "completed",
            "finished_at": ended,
            "candidate_count": candidate_count,
            "sample_size": len(checks),
            "metrics": metrics,
            "previous_run_id": previous.get("_id") if previous else None,
            "report_path": str(report_path),
        }
        repo.offer_verification_runs.update_one(
            {"_id": run_id},
            {"$set": run_update},
        )
        return {"run_id": str(run_id), **run_update}
    except Exception as exc:
        repo.offer_verification_runs.update_one(
            {"_id": run_id},
            {"$set": {
                "status": "failed",
                "finished_at": datetime.now(timezone.utc),
                "error": f"{type(exc).__name__}: {exc}"[:500],
            }},
        )
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-size", type=int, default=MAX_SAMPLE_SIZE)
    parser.add_argument("--report-directory", default=str(REPORT_DIRECTORY))
    args = parser.parse_args(argv)
    if not 1 <= args.sample_size <= MAX_SAMPLE_SIZE:
        parser.error(f"--sample-size debe estar entre 1 y {MAX_SAMPLE_SIZE}.")
    from retail.mongo import ProductRepository

    with ProductRepository() as repo:
        result = run_offer_verification(
            repo,
            sample_size=args.sample_size,
            report_directory=args.report_directory,
        )
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
