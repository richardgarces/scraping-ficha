"""API y etiquetas de recursos de hosts (BMAX / soyo / Orange Pi)."""

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from retail.host_stats import (
    _parse_docker_size,
    admin_hosts_payload,
    display_label,
    host_alerts,
)
from retail.web.app import app


@pytest.fixture
def repo(mongo_uri):
    from retail.mongo import ProductRepository

    repository = ProductRepository(mongo_uri, database=f"test_hosts_{uuid4().hex}")
    try:
        yield repository
    finally:
        repository.client.drop_database(repository.db.name)
        repository.close()


def test_display_label_known_ips_and_pi_hostname():
    assert display_label({"ip": "192.168.1.198", "hostname": "precios-web"}) == "BMAX"
    assert display_label({"ip": "192.168.1.197", "hostname": "soyo"}) == "soyo"
    assert display_label({"ip": "192.168.1.90", "hostname": "precios-cyber-pi"}) == "Orange Pi"
    assert display_label({"ip": None, "hostname": "precios-cyber-pi"}) == "Orange Pi"
    assert display_label({"ip": "10.0.0.1", "hostname": "mystery"}) == "mystery"


def test_parse_docker_size():
    assert _parse_docker_size("13.33GB") == 13_330_000_000
    assert _parse_docker_size("183.5GB (97%)") == 183_500_000_000
    assert abs((_parse_docker_size("355.9MB") or 0) - 355_900_000) < 2
    assert _parse_docker_size("") is None


def test_host_alerts_disk_ram_docker_stale():
    online = {
        "online": True,
        "disk": {"percent": 82, "free_bytes": 20 * 1024**3},
        "ram": {"percent": 91},
        "docker": {"reclaimable_bytes": 25 * 1000**3},
    }
    codes = {a["code"] for a in host_alerts(online)}
    assert "disk_warn" in codes
    assert "ram_warn" in codes
    assert "docker_reclaim" in codes

    hot = {"online": True, "disk": {"percent": 95, "free_bytes": 5 * 1024**3}, "ram": {}, "docker": {}}
    assert any(a["code"] == "disk_hot" for a in host_alerts(hot))

    stale = {"online": False, "reported_at": "2020-01-01T00:00:00+00:00"}
    assert host_alerts(stale)[0]["code"] == "stale"


def test_admin_hosts_payload_fixed_three_and_stale(repo):
    from datetime import datetime, timezone

    fresh = {
        "hostname": "precios-cyber-pi",
        "ip": "192.168.1.90",
        "reported_at": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": 3600,
        "cpu": {"percent": 12.0, "cores": 4, "load1": 0.5, "load5": 0.4, "load15": 0.3},
        "ram": {"used_bytes": 1, "free_bytes": 2, "total_bytes": 3, "percent": 33.0},
        "disk": {"path": "/", "used_bytes": 1, "free_bytes": 2, "total_bytes": 3, "percent": 10.0},
        "docker": {
            "images_bytes": 1_000_000_000,
            "images_reclaimable_bytes": 100_000_000,
            "reclaimable_bytes": 100_000_000,
        },
    }
    stale = {
        "hostname": "bmax",
        "ip": "192.168.1.198",
        "reported_at": "2000-01-01T00:00:00+00:00",
        "cpu": {"percent": 1.0},
        "ram": {"percent": 1.0},
        "disk": {"percent": 1.0},
    }
    repo.save_app_setting("cyber_day_host_stats:192.168.1.90", fresh)
    repo.save_app_setting("cyber_day_host_stats:192.168.1.198", stale)

    payload = admin_hosts_payload(repo)
    assert payload["ok"] is True
    assert [h["id"] for h in payload["hosts"]] == ["bmax", "soyo", "orange_pi"]
    by_id = {h["id"]: h for h in payload["hosts"]}
    assert by_id["bmax"]["label"] == "BMAX"
    assert by_id["bmax"]["role"]
    assert by_id["bmax"]["ssh"] == "ssh -p 2222 richard@192.168.1.198"
    assert by_id["bmax"]["image"] == "/static/hosts/bmax.png"
    assert by_id["soyo"]["image"] == "/static/hosts/soyo.jpg"
    assert by_id["orange_pi"]["image"] == "/static/hosts/orange-pi.jpg"
    assert by_id["bmax"]["stale"] is True
    assert by_id["bmax"]["online"] is False
    assert any(a["code"] == "stale" for a in by_id["bmax"]["alerts"])
    assert by_id["soyo"]["label"] == "soyo"
    assert by_id["soyo"]["stale"] is True
    assert by_id["soyo"]["online"] is False
    assert by_id["orange_pi"]["label"] == "Orange Pi"
    assert by_id["orange_pi"]["stale"] is False
    assert by_id["orange_pi"]["online"] is True
    assert by_id["orange_pi"]["cpu"]["percent"] == 12.0
    assert by_id["orange_pi"]["docker"]["images_bytes"] == 1_000_000_000
    assert by_id["orange_pi"]["role"] == "Cyber Day scrape"
    assert any(a["host_id"] == "bmax" for a in payload["alerts"])
    assert payload["thresholds"]["disk_warn"] == 80


def test_hosts_page_and_api_require_admin(anonymous_repo):
    client = TestClient(app)
    page = client.get("/hosts", follow_redirects=False)
    assert page.status_code in {302, 303}
    assert "/entrar" in (page.headers.get("location") or "")
    alias = client.get("/infra", follow_redirects=False)
    assert alias.status_code in {302, 303}
    assert client.get("/api/admin/hosts").status_code == 401


def test_hosts_static_assets():
    root = Path("retail/web/static")
    html = (root / "hosts.html").read_text(encoding="utf-8")
    js = (root / "hosts.js").read_text(encoding="utf-8")
    assert "<h1>Hosts</h1>" in html
    assert "Recursos de hosts" in html
    assert 'href="/hosts"' in html
    assert "data-admin" in html
    assert "hosts-grid" in html
    assert "hosts-alerts" in html
    assert "/api/admin/hosts" in js
    assert "BMAX" in html and "soyo" in html and "Orange Pi" in html
    assert "gaugeSvg" in js
    assert "hosts-card" in js
    assert "hosts-disk-free" in js
    assert "data-ssh" in js
    assert "ALERT_COMMANDS" in js
    assert "HOST_MAINTENANCE" in js
    assert "docker_reclaim" in js
    assert "ufw status" in js
    assert "apt upgrade" in js
    assert "data-copy" in js
    assert "hosts-cmd-copy" in js
    assert "hosts-maint-btn" in js
    assert "Mantenimiento" in html or "maintenancePanel" in js
    assert "hosts-photo" in js
    assert "host.image" in js
    assert (root / "hosts" / "bmax.png").is_file()
    assert (root / "hosts" / "soyo.jpg").is_file()
    assert (root / "hosts" / "orange-pi.jpg").is_file()
    assert "load1" in js and "load5" in js
    assert "docker" in js.lower()
    prices = (root / "prices.js").read_text(encoding="utf-8")
    assert 'href="/hosts"' in prices or '"/hosts"' in prices
    assert "Hosts" in prices
