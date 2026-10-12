from datetime import datetime, timezone
import random
from uuid import uuid4

import pytest
from bson import ObjectId

from retail.matching_audit import (
    _stratified_queries,
    arbitrate_matching_item,
    cohen_kappa,
    matching_audit_metrics,
    record_matching_review,
)
from retail.mongo import ProductRepository
from retail.offer_verification import (
    RobotsAwareSession,
    RobotsDenied,
    _differences,
    _markdown_report,
    summarize_checks,
)


def test_matching_audit_is_off_by_default_and_admin_controlled(monkeypatch):
    class SettingsRepository:
        def __init__(self):
            self.settings = {}

        def get_app_setting(self, key):
            return self.settings.get(key)

        def save_app_setting(self, key, value):
            self.settings[key] = value

        def close(self):
            pass

    from fastapi.testclient import TestClient

    from retail.web.app import app

    repo = SettingsRepository()
    admin = {"id": "admin-1", "role": "admin", "status": "approved"}
    monkeypatch.setattr("retail.web.deps.connect_repo", lambda: repo)
    monkeypatch.setattr("retail.web.deps.current_user", lambda *args, **kwargs: admin)
    monkeypatch.setattr("retail.web.app.connect_repo", lambda: repo)
    monkeypatch.setattr("retail.web.matching_audit_api.repo_or_503", lambda: repo)
    monkeypatch.setattr("retail.web.matching_audit_api.current_user", lambda *args, **kwargs: admin)
    monkeypatch.setattr("retail.web.settings_api.connect_repo", lambda: repo)
    monkeypatch.setattr("retail.web.settings_api.current_user", lambda *args, **kwargs: admin)

    client = TestClient(app)
    assert client.get("/static/prices.js").status_code == 200
    assert client.get("/auditoria-matching").status_code == 404
    assert client.get("/static/matching-audit.html").status_code == 404
    assert client.get("/api/admin/matching-audit/runs").status_code == 404

    enabled = client.put("/api/settings/matching-audit", json={"enabled": True})
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert client.get("/auditoria-matching").status_code == 200
    assert client.get("/static/matching-audit.html").status_code == 200

    disabled = client.put("/api/settings/matching-audit", json={"enabled": False})
    assert disabled.status_code == 200
    assert client.get("/auditoria-matching").status_code == 404


def test_stratified_sample_is_reproducible_and_respects_sample_size():
    rows = [
        {"category": category, "store": store, "frequency_bucket": bucket, "id": n}
        for n, (category, store, bucket) in enumerate(
            (category, store, bucket)
            for category in ("hogar", "tecnologia")
            for store in ("lider", "paris")
            for bucket in ("low", "medium", "high")
            for _ in range(4)
        )
    ]

    first, first_strata = _stratified_queries(rows, 17, random.Random(21))
    second, second_strata = _stratified_queries(rows, 17, random.Random(21))

    assert [row["id"] for row in first] == [row["id"] for row in second]
    assert first_strata == second_strata
    assert len(first) == 17
    assert sum(first_strata.values()) == 17
    assert len({row["id"] for row in first}) == 17


def test_cohen_kappa_multiclass_and_edge_cases():
    assert cohen_kappa(
        ["exact", "exact", "variant", "variant"],
        ["exact", "variant", "exact", "variant"],
    ) == pytest.approx(0)
    assert cohen_kappa([], []) is None
    assert cohen_kappa(["exact"], ["exact"]) == 1.0
    with pytest.raises(ValueError, match="etiquetas"):
        cohen_kappa(["unexpected"], ["exact"])


def test_matching_queue_shape_does_not_expose_reviewer_assignments():
    from retail.web.matching_audit_api import _public_item

    item = {
        "_id": ObjectId(),
        "run_id": ObjectId(),
        "search_id": ObjectId(),
        "reviewer_ids": ["reviewer-1"],
        "arbitrator_id": "reviewer-3",
        "arbitration_note": "internal",
    }
    public = _public_item(item)

    assert "reviewer_ids" not in public
    assert "arbitrator_id" not in public
    assert "arbitration_note" not in public


@pytest.fixture
def audit_repo(mongo_uri):
    repo = ProductRepository(mongo_uri, database=f"test_quality_audit_{uuid4().hex}")
    try:
        yield repo
    finally:
        repo.client.drop_database(repo.db.name)
        repo.close()


def test_matching_reviews_require_two_people_and_third_party_arbitration(audit_repo):
    run_id = audit_repo.matching_audit_runs.insert_one({"created_at": datetime.now(timezone.utc)}).inserted_id
    item_id = audit_repo.matching_audit_items.insert_one({
        "run_id": run_id,
        "status": "awaiting_reviews",
        "reviewer_ids": [],
        "created_at": datetime.now(timezone.utc),
    }).inserted_id

    assert record_matching_review(
        audit_repo, run_id=run_id, item_id=item_id,
        reviewer_id="reviewer-a", label="exact",
    )["status"] == "awaiting_second_review"
    with pytest.raises(ValueError, match="Ya registraste"):
        record_matching_review(
            audit_repo, run_id=run_id, item_id=item_id,
            reviewer_id="reviewer-a", label="exact",
        )
    assert record_matching_review(
        audit_repo, run_id=run_id, item_id=item_id,
        reviewer_id="reviewer-b", label="variant",
    )["status"] == "disagreement"
    with pytest.raises(ValueError, match="distinto"):
        arbitrate_matching_item(
            audit_repo, run_id=run_id, item_id=item_id,
            arbitrator_id="reviewer-a", label="exact",
        )
    assert arbitrate_matching_item(
        audit_repo, run_id=run_id, item_id=item_id,
        arbitrator_id="reviewer-c", label="exact", note="Se ve mismo modelo",
    )["status"] == "arbitrated"


def test_matching_kappa_groups_consistent_reviewer_pairs(audit_repo):
    run_id = ObjectId()
    audit_repo.matching_audit_runs.insert_one({"_id": run_id})
    for index, final_label in enumerate(("exact", "variant", "variant", "not_equivalent")):
        item_id = audit_repo.matching_audit_items.insert_one({
            "run_id": run_id, "search_id": ObjectId(), "store": "test",
            "product_id": str(index), "status": "agreed", "final_label": final_label,
        }).inserted_id
        pair = (
            ("a", final_label), ("b", final_label)
        ) if index < 2 else (
            (("c", "exact"), ("d", "variant"))
            if index == 2 else (("c", "variant"), ("d", "exact"))
        )
        for reviewer_id, label in pair:
            audit_repo.matching_audit_reviews.insert_one({
                "run_id": run_id, "item_id": item_id,
                "reviewer_id": reviewer_id, "label": label,
            })

    metrics = matching_audit_metrics(audit_repo, run_id)
    assert metrics["kappa_reviewer_pair_count"] == 2
    assert metrics["kappa_denominator"] == 4
    assert metrics["cohen_kappa"] == pytest.approx(0)


def test_offer_comparison_keeps_unverified_data_out_of_metrics():
    expected = {
        "price_all_payment": 1000,
        "stock": 3,
        "stock_verified": True,
        "shipping_region": "Santiago",
        "shipping_cost": 0,
    }
    observed = {
        "price_all_payment": 1200,
        "stock": 0,
        "stock_verified": False,
        "shipping_region": "Valparaíso",
        "shipping_cost": 1000,
    }
    differences = _differences(expected, observed)
    assert differences["price_all_payment"]["absolute_difference"] == 200
    assert differences["stock"]["status"] == "not_verified"
    assert differences["shipping_cost"]["status"] == "not_comparable"

    metrics = summarize_checks([
        {"url_status": "functional", "differences": differences},
        {"url_status": "not_verified", "differences": {}},
        {
            "url_status": "broken",
            "differences": {"price_all_payment": {
                "status": "verified", "discrepancy": False,
                "absolute_difference": 0, "relative_difference_percent": 0,
            }},
        },
    ])
    assert metrics["url_functional_percent"] == 50
    assert metrics["price_comparable_count"] == 2
    assert metrics["price_discrepancy_count"] == 1
    assert metrics["mean_absolute_price_difference"] == 200
    assert metrics["fields"]["stock"]["not_verified_count"] == 3


def test_offer_markdown_report_shows_sample_bases_and_check_timestamp():
    checked_at = datetime(2026, 2, 10, 15, tzinfo=timezone.utc)
    checks = [{
        "store": "tienda",
        "name": "Producto | formato\nespecial",
        "checked_at": checked_at,
        "differences": {
            "price_all_payment": {
                "status": "verified",
                "expected": 1000,
                "observed": 1200,
                "discrepancy": True,
                "absolute_difference": 200,
                "relative_difference_percent": 20,
            }
        },
    }]
    metrics = summarize_checks(checks)
    report = _markdown_report(
        {"id": "run-1", "started_at": checked_at, "candidate_count": 4},
        checks,
        metrics,
        None,
    )

    assert "4" in report and "Muestra revisada: 1" in report
    assert "100.0%" in report
    assert "$200" in report
    assert "Producto \\| formato especial" in report
    assert "2026-02-10" in report
    assert "No hay una corrida completada" in report


def test_robots_adapter_blocks_disallowed_paths_before_request(monkeypatch):
    class Rules:
        @staticmethod
        def can_fetch(_agent, url):
            return not url.endswith("/blocked")

    class Response:
        status_code = 200
        headers = {"content-type": "text/html"}
        text = "ok"

        def __init__(self, url):
            self.url = url

    class Client:
        def __init__(self):
            self.requested = []

        def request(self, method, url, **_kwargs):
            self.requested.append((method, url))
            return Response(url)

        def close(self):
            pass

    host = f"shop-{uuid4().hex}.example"
    session = RobotsAwareSession(store=host, allowed_hosts={host})
    client = Client()
    session._client.close()
    session._client = client
    session._robots_rules = lambda _origin: (Rules(), 2.0)
    waits = []
    ticks = iter((1.0, 1.5))
    monkeypatch.setattr("retail.offer_verification.time.monotonic", lambda: next(ticks))
    monkeypatch.setattr("retail.offer_verification.time.sleep", waits.append)

    assert session.get(f"https://{host}/product")[0] == 200
    assert session.get(f"https://{host}/second-product")[0] == 200
    with pytest.raises(RobotsDenied, match="robots_disallowed"):
        session.get(f"https://{host}/blocked")
    assert client.requested == [
        ("GET", f"https://{host}/product"),
        ("GET", f"https://{host}/second-product"),
    ]
    assert waits == [1.5]
    session.close()
