"""Ofertas de hoy: no repetir productos ya listados en días anteriores."""

from __future__ import annotations

from retail.mongo import ProductRepository


class _Cursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def limit(self, _n):
        return self

    def __iter__(self):
        return iter(self.docs)


class _Alerts:
    def __init__(self, docs):
        self.docs = [dict(item) for item in docs]

    def find(self, query, projection=None):
        day_lt = (query.get("day") or {}).get("$lt") if isinstance(query.get("day"), dict) else None
        day_eq = query.get("day") if isinstance(query.get("day"), str) else None
        codes = (query.get("compare_code") or {}).get("$in") if isinstance(query.get("compare_code"), dict) else None
        rows = []
        for item in self.docs:
            if day_lt is not None and not (str(item.get("day") or "") < day_lt):
                continue
            if day_eq is not None and item.get("day") != day_eq:
                continue
            if codes is not None and item.get("compare_code") not in codes:
                continue
            if "$or" in query:
                matched = False
                for clause in query["$or"]:
                    ok = True
                    for key, value in clause.items():
                        if key == "extra.product_id":
                            if (item.get("extra") or {}).get("product_id") != value:
                                ok = False
                                break
                        elif item.get(key) != value:
                            ok = False
                            break
                    if ok:
                        matched = True
                        break
                if not matched:
                    continue
            rows.append(dict(item))
        return _Cursor(rows)

    def count_documents(self, query, limit=0):
        return len(list(self.find(query)))


def test_deal_identity_prefers_compare_code_then_product():
    assert ProductRepository._deal_identity_key({"compare_code": "abc", "store": "falabella"}) == "c:abc"
    assert (
        ProductRepository._deal_identity_key(
            {"store": "Falabella", "extra": {"product_id": "p1"}}
        )
        == "p:falabella|p1"
    )
    assert ProductRepository._deal_identity_key({"store": "lider", "name": "Leche"}) == "n:lider|leche"


def test_deals_hides_products_already_seen_on_earlier_days():
    docs = [
        {
            "_id": "old",
            "day": "2026-09-30",
            "store": "falabella",
            "compare_code": "tv-1",
            "name": "TV vieja",
            "saving": 10000,
            "previous_price": 200000,
            "price": 190000,
            "extra": {},
        },
        {
            "_id": "repeat",
            "day": "2026-10-01",
            "store": "falabella",
            "compare_code": "tv-1",
            "name": "TV vieja",
            "saving": 12000,
            "previous_price": 200000,
            "price": 188000,
            "extra": {},
        },
        {
            "_id": "fresh",
            "day": "2026-10-01",
            "store": "paris",
            "compare_code": "phone-2",
            "name": "Celular nuevo",
            "saving": 50000,
            "previous_price": 400000,
            "price": 350000,
            "extra": {},
        },
        {
            "_id": "fresh-dup",
            "day": "2026-10-01",
            "store": "paris",
            "compare_code": "phone-2",
            "name": "Celular nuevo otra vez",
            "saving": 51000,
            "previous_price": 400000,
            "price": 349000,
            "extra": {},
        },
    ]
    repo = ProductRepository.__new__(ProductRepository)
    repo.alerts = _Alerts(docs)
    found = repo.deals(day="2026-10-01")
    assert found["total"] == 1
    assert found["items"][0]["compare_code"] == "phone-2"
    assert found["items"][0]["id"] == "fresh"


def test_alert_exists_looks_beyond_today():
    class Alert:
        compare_code = "tv-1"
        store = "falabella"
        name = "TV"
        extra = {}

    repo = ProductRepository.__new__(ProductRepository)
    repo.alerts = _Alerts(
        [{"day": "2026-09-28", "compare_code": "tv-1", "store": "falabella", "name": "TV", "extra": {}}]
    )
    assert repo.alert_exists(Alert()) is True
    repo.alerts = _Alerts([])
    assert repo.alert_exists(Alert()) is False


def test_deals_corrects_legacy_below_median_discount():
    repo = ProductRepository.__new__(ProductRepository)
    repo.alerts = _Alerts([{
        "_id": "legacy-puma",
        "day": "2026-10-02",
        "store": "maxservice",
        "name": "Puma",
        "price": 95192,
        "price_normal": 118990,
        "reference_price": 118990,
        "analysis_reference_price": 190990,
        "previous_price": 118990,
        "saving": 23798,
        "discount": 20.0,
        "rule": "below_median",
        "extra": {
            "product_id": "300000671",
            "median": 190990,
            "percent_vs_median": -50.2,
        },
    }])

    found = repo.deals(day="2026-10-02")
    assert found["items"][0]["discount"] == 20.0
    assert found["items"][0]["saving"] == 23798
    assert found["items"][0]["reference_price"] == 118990
    assert found["items"][0]["analysis_reference_price"] == 190990
    assert found["items"][0]["analysis_discount_pct"] == 50.2
