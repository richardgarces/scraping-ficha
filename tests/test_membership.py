"""Cupos de alertas, roles y mes de regalo de membresía."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from retail.membership import (
    ALERT_LIMITS,
    ADMIN_ALERT_LIMIT,
    alert_limit_for,
    alert_quota,
    check_can_activate_alert,
    effective_tier,
    grant_gift_month,
    has_advanced_account_prefs,
    membership_active,
    membership_public,
    redeem_promo_code,
    set_user_role,
)
from retail.web.app import app


class MemStore:
    def __init__(self):
        self.users = []
        self.price_alerts = []
        self._n = 0

    def find_user_by_id(self, user_id):
        return next((item for item in self.users if str(item.get("_id")) == str(user_id)), None)

    def insert_user(self, data):
        self._n += 1
        row = dict(data)
        row["_id"] = str(self._n)
        self.users.append(row)
        return row

    def update_user(self, user_id, fields):
        found = self.find_user_by_id(user_id)
        if not found:
            return None
        found.update(fields)
        return found

    def _public_user(self, item):
        if not item:
            return None
        return {
            "id": str(item.get("_id") or ""),
            "email": item.get("email"),
            "name": item.get("name") or "",
            "role": item.get("role") or "user",
            "status": item.get("status") or "pending",
            "membership": membership_public(item),
        }

    def count_price_alerts(self, user_id):
        return sum(
            1
            for item in self.price_alerts
            if str(item.get("user_id")) == str(user_id) and item.get("active") is True
        )

    def list_price_alerts(self, user_id, *, active_only=True):
        rows = []
        for item in self.price_alerts:
            if str(item.get("user_id")) != str(user_id):
                continue
            if active_only and item.get("active") is not True:
                continue
            rows.append(dict(item))
        return rows

    def get_price_alert(self, user_id, store, product_id):

        for item in self.price_alerts:
            if (
                str(item.get("user_id")) == str(user_id)
                and item.get("store") == store
                and item.get("product_id") == product_id
                and item.get("active") is True
            ):
                return item
        return None


def test_alert_limits_by_tier():
    assert alert_limit_for({"role": "user"}) == 3
    assert alert_limit_for({
        "role": "paid",
        "membership_expires_at": datetime.now(timezone.utc) + timedelta(days=5),
    }) == 20
    assert alert_limit_for({"role": "admin"}) == ADMIN_ALERT_LIMIT
    assert ALERT_LIMITS["user"] == 3
    assert ALERT_LIMITS["paid"] == 20


def test_expired_paid_falls_back_to_user_limit():
    past = datetime.now(timezone.utc) - timedelta(days=1)
    doc = {"role": "paid", "membership_expires_at": past}
    assert membership_active(doc) is False
    assert effective_tier(doc) == "user"
    assert alert_limit_for(doc) == 3


def test_gift_month_extends_from_current_expiry():
    store = MemStore()
    now = datetime.now(timezone.utc)
    user = store.insert_user({
        "email": "ana@example.com",
        "role": "user",
        "status": "approved",
        "membership_expires_at": now + timedelta(days=10),
        "membership_plan": "monthly",
        "membership_source": "paid",
    })
    public = grant_gift_month(store, user["_id"], months=1, actor_id="admin-1")
    assert public["role"] == "paid"
    assert public["membership"]["active"] is True
    assert public["membership"]["source"] == "gift"
    refreshed = store.find_user_by_id(user["_id"])
    expires = refreshed["membership_expires_at"]
    # 10 días restantes + 30 de regalo ≈ 40 días
    assert expires > now + timedelta(days=38)
    assert refreshed["membership_gift_months"] == 1


def test_gift_month_from_scratch_sets_paid():
    store = MemStore()
    user = store.insert_user({"email": "bob@example.com", "role": "user", "status": "approved"})
    public = grant_gift_month(store, user["_id"], months=1)
    assert public["role"] == "paid"
    assert public["membership"]["active"] is True
    assert public["membership"]["alert_limit"] == 20


def test_admin_role_untouched_by_gift():
    store = MemStore()
    user = store.insert_user({"email": "admin@example.com", "role": "admin", "status": "approved"})
    public = grant_gift_month(store, user["_id"], months=1)
    assert public["role"] == "admin"
    assert public["membership"]["tier"] == "admin"


def test_count_price_alerts_only_active_for_user():
    store = MemStore()
    user = store.insert_user({"email": "a@example.com", "role": "user", "status": "approved"})
    other = store.insert_user({"email": "b@example.com", "role": "user", "status": "approved"})
    uid = user["_id"]
    store.price_alerts.append({"user_id": uid, "store": "lider", "product_id": "p1", "active": True})
    store.price_alerts.append({"user_id": uid, "store": "lider", "product_id": "p2", "active": False})
    store.price_alerts.append({"user_id": other["_id"], "store": "lider", "product_id": "p3", "active": True})
    public = store._public_user(user)
    quota = alert_quota(store, public)
    assert quota["count"] == 1
    assert store.count_price_alerts(uid) == 1


def test_quota_blocks_fourth_alert_for_free_user():
    store = MemStore()
    user = store.insert_user({
        "email": "free@example.com",
        "role": "user",
        "status": "approved",
    })
    uid = user["_id"]
    for i in range(3):
        store.price_alerts.append({
            "user_id": uid, "store": "lider", "product_id": f"p{i}", "active": True,
        })
    public = store._public_user(user)
    public["email"] = "free@example.com"
    quota = alert_quota(store, public, store="lider", product_id="p-new")
    assert quota["can_add"] is False
    assert quota["limit"] == 3
    assert quota["upgrade"] is True
    ok, detail = check_can_activate_alert(store, public, store="lider", product_id="p-new")
    assert ok is False
    assert isinstance(detail, dict)
    assert detail["code"] == "alert_limit"


def test_quota_allows_existing_alert_without_consuming():
    store = MemStore()
    user = store.insert_user({"email": "a@example.com", "role": "user", "status": "approved"})
    uid = user["_id"]
    for i in range(3):
        store.price_alerts.append({
            "user_id": uid, "store": "lider", "product_id": f"p{i}", "active": True,
        })
    public = store._public_user(user)
    public["email"] = "a@example.com"
    quota = alert_quota(store, public, store="lider", product_id="p1")
    assert quota["already"] is True
    assert quota["can_add"] is True


def test_paid_quota_allows_up_to_20():
    store = MemStore()
    user = store.insert_user({
        "email": "paid@example.com",
        "role": "paid",
        "status": "approved",
        "membership_expires_at": datetime.now(timezone.utc) + timedelta(days=20),
    })
    uid = user["_id"]
    for i in range(19):
        store.price_alerts.append({
            "user_id": uid, "store": "lider", "product_id": f"p{i}", "active": True,
        })
    public = store._public_user(user)
    public["email"] = "paid@example.com"
    assert alert_quota(store, public, store="lider", product_id="p-new")["can_add"] is True
    store.price_alerts.append({
        "user_id": uid, "store": "lider", "product_id": "p19", "active": True,
    })
    assert alert_quota(store, public, store="lider", product_id="p-new")["can_add"] is False


def test_promo_code_once_per_user(monkeypatch):
    monkeypatch.setenv("RETAIL_MEMBERSHIP_PROMO_CODES", "REGALO1MES,OTRO")
    store = MemStore()
    user = store.insert_user({"email": "promo@example.com", "role": "user", "status": "approved"})
    first = redeem_promo_code(store, user["_id"], "regalo1mes")
    assert first["role"] == "paid"
    assert first["membership"]["active"] is True
    with pytest.raises(ValueError, match="Ya usaste"):
        redeem_promo_code(store, user["_id"], "OTRO")


def test_set_role_paid_grants_month():
    store = MemStore()
    user = store.insert_user({"email": "x@example.com", "role": "user", "status": "approved"})
    public = set_user_role(store, user["_id"], "paid", actor_id="1")
    assert public["role"] == "paid"
    assert public["membership"]["active"] is True


def test_set_role_user_ends_membership():
    store = MemStore()
    user = store.insert_user({
        "email": "y@example.com",
        "role": "paid",
        "status": "approved",
        "membership_expires_at": datetime.now(timezone.utc) + timedelta(days=15),
    })
    public = set_user_role(store, user["_id"], "user", actor_id="1")
    assert public["role"] == "user"
    assert public["membership"]["active"] is False
    assert alert_limit_for(store.find_user_by_id(user["_id"])) == 3


def test_list_price_alerts_api_only_own_active(monkeypatch):
    store = MemStore()
    user = store.insert_user({
        "email": "list@example.com",
        "role": "user",
        "status": "approved",
    })
    other = store.insert_user({
        "email": "other@example.com",
        "role": "user",
        "status": "approved",
    })
    uid = str(user["_id"])
    store.price_alerts.append({
        "user_id": uid, "store": "lider", "product_id": "a1", "active": True, "name": "A",
    })
    store.price_alerts.append({
        "user_id": uid, "store": "lider", "product_id": "a2", "active": False, "name": "B",
    })
    store.price_alerts.append({
        "user_id": str(other["_id"]), "store": "lider", "product_id": "a3", "active": True, "name": "C",
    })

    class Repo(MemStore):
        def __init__(self, base):
            self.users = base.users
            self.price_alerts = base.price_alerts
            self._n = base._n

        def close(self):
            return None

    repo = Repo(store)
    public = store._public_user(user) | {"id": uid, "email": "list@example.com"}
    monkeypatch.setattr("retail.web.insights_api.connect_repo", lambda: repo)
    monkeypatch.setattr("retail.web.insights_api.current_user", lambda *a, **k: public)

    client = TestClient(app)
    response = client.get("/api/price-alerts")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["product_id"] == "a1"


def test_activate_price_alert_api_enforces_limit(monkeypatch):

    store = MemStore()
    user = store.insert_user({
        "email": "limit@example.com",
        "role": "user",
        "status": "approved",
        "notification_preferences": {"channels": ["email"], "kinds": ["watch"]},
    })
    uid = user["_id"]
    for i in range(3):
        store.price_alerts.append({
            "user_id": uid, "store": "lider", "product_id": f"sku-{i}", "active": True,
        })

    class Repo(MemStore):
        def __init__(self, base):
            self.users = base.users
            self.price_alerts = base.price_alerts
            self._n = base._n

        def product_detail(self, store, product_id):
            return {"name": "X", "url": "https://example.com", "store": store, "product_id": product_id}

        def save_price_alert(self, data):
            self.price_alerts.append({**data, "active": True})
            return data

        def close(self):
            return None

    repo = Repo(store)
    monkeypatch.setattr("retail.web.insights_api.connect_repo", lambda: repo)
    monkeypatch.setattr(
        "retail.web.insights_api.current_user",
        lambda *a, **k: store._public_user(user) | {"email": "limit@example.com", "id": uid},
    )
    monkeypatch.setattr(
        "retail.user_alert_list.add_user_alert",
        lambda *a, **k: {"ok": True},
    )
    client = TestClient(app)
    response = client.post(
        "/api/price-alert",
        json={"store": "lider", "product_id": "sku-new", "name": "Nuevo"},
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "alert_limit"
    assert detail["limit"] == 3
    assert detail["upgrade"] is True


def test_has_advanced_account_prefs_by_tier():
    assert has_advanced_account_prefs({"role": "user"}) is False
    assert has_advanced_account_prefs({
        "role": "paid",
        "membership_expires_at": datetime.now(timezone.utc) + timedelta(days=3),
    }) is True
    assert has_advanced_account_prefs({
        "role": "paid",
        "membership_expires_at": datetime.now(timezone.utc) - timedelta(days=1),
    }) is False
    assert has_advanced_account_prefs({"role": "admin"}) is True


def test_free_user_cannot_put_advanced_notification_prefs(monkeypatch):
    store = MemStore()
    user = store.insert_user({
        "email": "free@example.com",
        "role": "user",
        "status": "approved",
        "notification_preferences": {"channels": ["email"], "kinds": ["watch"]},
    })
    uid = str(user["_id"])

    class Repo(MemStore):
        def __init__(self, base):
            self.users = base.users
            self.price_alerts = base.price_alerts
            self._n = base._n

        def update_user_fields(self, user_id, fields, *, unset=()):
            found = self.find_user_by_id(user_id)
            if not found:
                return None
            found.update(fields)
            for key in unset:
                found.pop(key, None)
            return found

        def close(self):
            return None

    repo = Repo(store)
    public = store._public_user(user) | {"id": uid}
    monkeypatch.setattr("retail.web.auth_api.repo_or_503", lambda: repo)
    monkeypatch.setattr("retail.web.auth_api.current_user", lambda *a, **k: public)
    monkeypatch.setattr("retail.web.auth_api.list_store_categories", lambda repo=None: [])
    monkeypatch.setattr(
        "retail.web.auth_api._predictive_status",
        lambda *_a, **_k: {"enabled": False, "reason": "test"},
    )

    client = TestClient(app)
    denied = client.put(
        "/api/account/notifications",
        json={
            "telegram": "",
            "preferences": {
                "channels": ["email"],
                "kinds": ["watch"],
                "email_categories": ["tecnologia"],
                "min_discount_self": 5,
            },
        },
    )
    assert denied.status_code == 403
    detail = denied.json()["detail"]
    assert detail["code"] == "membership_required"
    assert "email_categories" in detail["keys"]

    allowed = client.put(
        "/api/account/notifications",
        json={
            "telegram": "",
            "preferences": {"channels": ["email", "push"], "kinds": ["watch", "real"]},
        },
    )
    assert allowed.status_code == 200
    prefs = allowed.json()["preferences"]
    assert prefs["channels"] == ["email", "push"]
    assert prefs["kinds"] == ["watch", "real"]
    assert prefs["email_categories"] == []
    assert prefs["min_discount_self"] == 0.0

    store_denied = client.put(
        "/api/account/store-preferences",
        json={"favorites": ["falabella"], "excluded": []},
    )
    assert store_denied.status_code == 403
    assert store_denied.json()["detail"]["code"] == "membership_required"
