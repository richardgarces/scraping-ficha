from retail.price_alerts import price_change_message, price_deltas
from retail.price_alerts import notify_price_changes


class _Product:
    def __init__(self, store, product_id, price, name="Auriculares", image_url=None):
        self.store = store
        self.product_id = product_id
        self.price = price
        self.name = name
        self.url = "https://tienda.example/p"
        self.image_url = image_url


def test_price_deltas_ignores_first_sight_and_same_price():
    product = _Product("falabella", "p1", 1990)
    assert price_deltas({}, [product]) == []
    same = price_deltas({("falabella", "p1"): (1990, "2026-09-16")}, [product])
    assert same == []


def test_price_deltas_covers_up_and_down():
    down = price_deltas(
        {("falabella", "p1"): (2000, "2026-09-15")},
        [_Product("falabella", "p1", 1500)],
    )
    up = price_deltas(
        {("lider", "p2"): (900, "2026-09-15")},
        [_Product("lider", "p2", 1100, name="Notebook")],
    )
    assert down[0]["previous_price"] == 2000
    assert down[0]["price"] == 1500
    assert up[0]["price"] == 1100
    assert up[0]["name"] == "Notebook"


def test_price_delta_keeps_product_image():
    changes = price_deltas(
        {("falabella", "p1"): (2000, "2026-09-15")},
        [_Product("falabella", "p1", 1500, image_url="https://example.com/producto.jpg")],
    )
    assert changes[0]["image_url"] == "https://example.com/producto.jpg"


def test_price_change_message_is_spanish_and_links_ficha():
    subject, body = price_change_message(
        {
            "name": "Audífonos Sony",
            "store": "falabella",
            "product_id": "sku 1",
            "previous_price": 20000,
            "price": 15000,
        }
    )
    assert subject.startswith("Cambió el precio:")
    assert "Audífonos Sony" in body
    assert "Tienda:" in body
    assert "Precio anterior: $20.000" in body
    assert "Precio nuevo: $15.000" in body
    assert "bajó" in body
    assert "/producto?store=falabella&id=sku%201" in body


def test_notify_sends_once_per_change(monkeypatch):
    sent = []

    def fake_send(to_addr, subject, body, *, log_skip=False, **kwargs):
        sent.append((to_addr, subject, body, kwargs))
        return True

    monkeypatch.setattr("retail.price_alerts.send_email", fake_send)
    monkeypatch.setattr(
        "retail.batch.rules.load_rules",
        lambda: {"channels": ["log", "file", "telegram", "email"]},
    )
    claimed = set()

    class Repo:
        price_alerts = object()

        def price_alerts_for(self, keys):
            return [
                {
                    "user_id": "u1",
                    "store": "falabella",
                    "product_id": "p1",
                    "email": "ana@example.com",
                    "active": True,
                }
            ]

        def claim_price_alert_send(self, user_id, store, product_id, previous_price, price, *, channel="email"):
            key = (user_id, channel, store, product_id, price)
            if key in claimed:
                return False
            claimed.add(key)
            return True

        def find_user_by_id(self, user_id):
            return {"email": "ana@example.com", "status": "approved"}

    change = {
        "store": "falabella",
        "product_id": "p1",
        "name": "Audífonos",
        "previous_price": 2000,
        "price": 1500,
    }
    repo = Repo()
    assert notify_price_changes(repo, [change]) == 1
    assert notify_price_changes(repo, [change]) == 0
    assert len(sent) == 1
    assert sent[0][0] == "ana@example.com"
    assert "Precio anterior" in sent[0][2]
    assert "Ver ficha del producto" in sent[0][3]["html"]
    assert "Audífonos" in sent[0][3]["html"]


def test_notify_skips_email_when_admin_correo_disabled(monkeypatch):
    sent = []
    monkeypatch.setattr(
        "retail.price_alerts.send_email",
        lambda *args, **kwargs: sent.append(args) or True,
    )
    monkeypatch.setattr(
        "retail.batch.rules.load_rules",
        lambda: {"channels": ["log", "file", "telegram"]},
    )

    class Repo:
        price_alerts = object()

        def price_alerts_for(self, keys):
            return [
                {
                    "user_id": "u1",
                    "store": "falabella",
                    "product_id": "p1",
                    "email": "ana@example.com",
                    "active": True,
                }
            ]

        def claim_price_alert_send(self, *args, **kwargs):
            return True

        def find_user_by_id(self, user_id):
            return {"email": "ana@example.com", "status": "approved"}

    assert notify_price_changes(
        Repo(),
        [{"store": "falabella", "product_id": "p1", "name": "TV", "previous_price": 2000, "price": 1500}],
    ) == 0
    assert sent == []


def test_notify_accepts_a_pymongo_collection_without_boolean_evaluation(monkeypatch):
    class CollectionLike:
        def __bool__(self):
            raise NotImplementedError("Collection objects do not implement truth value testing")

    class Repo:
        price_alerts = CollectionLike()

        def price_alerts_for(self, keys):
            return []

        def claim_price_alert_send(self, *args, **kwargs):
            return False

    assert notify_price_changes(
        Repo(),
        [{"store": "lider", "product_id": "p1", "previous_price": 1000, "price": 900}],
    ) == 0


def test_notify_skips_clearly_when_smtp_missing(monkeypatch, capsys):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setattr("retail.batch.alerts.load_channels", lambda: {})
    monkeypatch.setattr(
        "retail.batch.rules.load_rules",
        lambda: {"channels": ["log", "file", "email"]},
    )

    class Repo:
        price_alerts = object()

        def price_alerts_for(self, keys):
            return [{"user_id": "u1", "store": "lider", "product_id": "p9", "email": "ana@example.com", "active": True}]

        def claim_price_alert_send(self, *args, **kwargs):
            return True

        def find_user_by_id(self, user_id):
            return {"email": "ana@example.com", "status": "approved"}

    sent = notify_price_changes(
        Repo(),
        [{"store": "lider", "product_id": "p9", "name": "TV", "previous_price": 10, "price": 12}],
    )
    assert sent == 0
    assert "SMTP no configurado" in capsys.readouterr().out


def test_upsert_notifies_only_when_price_changes(monkeypatch):
    from retail.mongo import ProductRepository

    calls = []
    monkeypatch.setattr(
        "retail.price_alerts.notify_price_changes",
        lambda repo, changes: calls.append(changes) or len(changes),
    )

    class MemCollection:
        def __init__(self):
            self.docs = []

        def find(self, query, projection=None):
            wanted = {
                (item.get("store"), item.get("product_id"))
                for item in (query or {}).get("$or") or []
            }
            for doc in self.docs:
                if (doc.get("store"), doc.get("product_id")) in wanted:
                    yield doc

        def bulk_write(self, operations, ordered=False):
            upserted = modified = matched = 0
            for op in operations:
                filt = op._filter
                update = op._doc
                existing = next(
                    (
                        doc
                        for doc in self.docs
                        if doc.get("store") == filt.get("store") and doc.get("product_id") == filt.get("product_id")
                    ),
                    None,
                )
                if existing is None and op._upsert:
                    doc = {}
                    doc.update(update.get("$setOnInsert") or {})
                    doc.update(update.get("$set") or {})
                    if "$push" in update:
                        doc["price_history"] = list(update["$push"]["price_history"]["$each"])
                    self.docs.append(doc)
                    upserted += 1
                elif existing is not None:
                    existing.update(update.get("$set") or {})
                    if "$push" in update:
                        existing.setdefault("price_history", []).extend(update["$push"]["price_history"]["$each"])
                    matched += 1
                    modified += 1

            class Result:
                upserted_count = upserted
                modified_count = modified
                matched_count = matched

            return Result()

    repo = ProductRepository.__new__(ProductRepository)
    repo.collection = MemCollection()
    repo.price_alerts = object()
    offer = {
        "store": "ahumada",
        "product_id": "para-500",
        "sku_id": "para-500",
        "name": "Paracetamol 500",
        "price": 1990,
        "currency": "CLP",
    }
    repo.upsert_offers([offer], "paracetamol")
    assert calls == []
    repo.upsert_offers([{**offer, "price": 1490}], "paracetamol")
    assert calls[-1][0]["previous_price"] == 1990
    assert calls[-1][0]["price"] == 1490
    repo.upsert_offers([{**offer, "price": 1490}], "paracetamol")
    assert len(calls) == 1
    repo.upsert_offers([{**offer, "price": 2100}], "paracetamol")
    assert calls[-1][0]["previous_price"] == 1490
    assert calls[-1][0]["price"] == 2100
