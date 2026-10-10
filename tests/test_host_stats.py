"""API y etiquetas de recursos de hosts (BMAX / soyo / Orange Pi)."""

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from retail.host_stats import (
    _milli_celsius_to_c,
    _normalize_facts,
    _parse_docker_size,
    admin_hosts_payload,
    collect_host_facts,
    collect_temperature,
    display_label,
    host_alerts,
    merge_host_history,
    report_host_stats,
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


def test_milli_celsius_to_c():
    assert _milli_celsius_to_c(45200) == 45.2
    # Valores pequeños (<200) se interpretan como °C ya convertidos.
    assert _milli_celsius_to_c(85) == 85.0
    assert _milli_celsius_to_c(200_000) is None


def test_collect_temperature_from_env(monkeypatch):
    monkeypatch.setenv("HOST_STATS_TEMP_C", "47.5")
    monkeypatch.setenv("HOST_STATS_TEMP_SOURCE", "x86_pkg_temp")
    monkeypatch.setattr("retail.host_stats._read_thermal_zones", lambda: [])
    monkeypatch.setattr("retail.host_stats._read_hwmon_temps", lambda: [])
    assert collect_temperature() == {"celsius": 47.5, "source": "x86_pkg_temp"}


def test_collect_temperature_prefers_cpu_thermal(monkeypatch):
    monkeypatch.delenv("HOST_STATS_TEMP_C", raising=False)
    monkeypatch.delenv("HOST_STATS_TEMP_SOURCE", raising=False)
    monkeypatch.setattr(
        "retail.host_stats._read_thermal_zones",
        lambda: [(50, "acpitz", 38.0), (3, "cpu-thermal", 52.0)],
    )
    monkeypatch.setattr("retail.host_stats._read_hwmon_temps", lambda: [])
    assert collect_temperature() == {"celsius": 52.0, "source": "cpu-thermal"}


def test_collect_temperature_none_when_unavailable(monkeypatch):
    monkeypatch.delenv("HOST_STATS_TEMP_C", raising=False)
    monkeypatch.setattr("retail.host_stats._read_thermal_zones", lambda: [])
    monkeypatch.setattr("retail.host_stats._read_hwmon_temps", lambda: [])
    assert collect_temperature() is None


def test_normalize_facts_graceful_nulls():
    assert _normalize_facts(None)["cpu_model"] is None
    assert _normalize_facts({"cpu_cores": "8", "mem_total_bytes": "1024"})["cpu_cores"] == 8
    assert _normalize_facts({"uptime_seconds": "12.34"})["uptime_seconds"] == 12.3
    assert _normalize_facts({"hostname": "  "})["hostname"] is None


def test_collect_host_facts_from_env_json(monkeypatch):
    payload = {
        "hostname": "bmax",
        "cpu_model": "AMD Ryzen 9",
        "cpu_cores": 16,
        "cpu_arch": "x86_64",
        "mem_total_bytes": 64 * 1024**3,
        "disk_total_bytes": 2 * 1024**4,
        "os_pretty_name": "Ubuntu 24.04.1 LTS",
        "kernel": "6.8.0-71-generic",
        "uptime_seconds": 12345.6,
        "machine_model": "Custom PC",
    }
    monkeypatch.setenv("HOST_STATS_FACTS", __import__("json").dumps(payload))
    monkeypatch.delenv("HOST_STATS_FACTS_B64", raising=False)
    facts = collect_host_facts()
    assert facts["hostname"] == "bmax"
    assert facts["cpu_model"] == "AMD Ryzen 9"
    assert facts["cpu_cores"] == 16
    assert facts["cpu_arch"] == "x86_64"
    assert facts["os_pretty_name"] == "Ubuntu 24.04.1 LTS"
    assert facts["kernel"] == "6.8.0-71-generic"
    assert facts["machine_model"] == "Custom PC"
    assert facts["mem_total_bytes"] == 64 * 1024**3
    assert facts["disk_total_bytes"] == 2 * 1024**4
    assert facts["uptime_seconds"] == 12345.6


def test_collect_host_facts_from_env_b64(monkeypatch):
    import base64
    import json

    raw = json.dumps({"hostname": "soyo", "cpu_arch": "x86_64", "cpu_cores": 8})
    monkeypatch.delenv("HOST_STATS_FACTS", raising=False)
    monkeypatch.setenv("HOST_STATS_FACTS_B64", base64.b64encode(raw.encode()).decode())
    facts = collect_host_facts()
    assert facts["hostname"] == "soyo"
    assert facts["cpu_cores"] == 8
    assert facts["os_pretty_name"] is None


def test_collect_host_facts_local_keys(monkeypatch):
    monkeypatch.delenv("HOST_STATS_FACTS", raising=False)
    monkeypatch.delenv("HOST_STATS_FACTS_B64", raising=False)
    facts = collect_host_facts()
    assert set(facts) == {
        "hostname",
        "cpu_model",
        "cpu_cores",
        "cpu_arch",
        "mem_total_bytes",
        "disk_total_bytes",
        "os_pretty_name",
        "kernel",
        "uptime_seconds",
        "machine_model",
    }
    # En CI/macOS varios campos pueden ser null; cores suele existir.
    assert facts["cpu_cores"] is None or facts["cpu_cores"] >= 1


def test_merge_host_history_appends_and_caps():
    base = {
        "reported_at": "2026-10-10T12:00:00+00:00",
        "cpu": {"percent": 10.0},
        "ram": {"percent": 40.0},
        "disk": {"percent": 50.0},
        "temperature": {"celsius": 45.0, "source": "cpu-thermal"},
        "docker": {"reclaimable_bytes": 1_000_000},
    }
    first = merge_host_history(None, base, max_points=3, max_age_seconds=86400)
    assert len(first) == 1
    assert first[0]["temp"] == 45.0
    assert first[0]["cpu"] == 10.0
    assert first[0]["dkr"] == 1_000_000

    prev = {"history": first}
    second_stats = {
        **base,
        "reported_at": "2026-10-10T12:01:00+00:00",
        "cpu": {"percent": 20.0},
        "temperature": {"celsius": 50.0, "source": "cpu-thermal"},
    }
    second = merge_host_history(prev, second_stats, max_points=3, max_age_seconds=86400)
    assert len(second) == 2
    assert second[-1]["temp"] == 50.0
    assert second[-1]["cpu"] == 20.0

    # Cap: keep last 3
    hist = second
    for i in range(3, 6):
        hist = merge_host_history(
            {"history": hist},
            {
                **base,
                "reported_at": f"2026-10-10T12:0{i}:00+00:00",
                "temperature": {"celsius": 40.0 + i, "source": "x"},
            },
            max_points=3,
            max_age_seconds=86400,
        )
    assert len(hist) == 3
    assert hist[0]["t"] == "2026-10-10T12:03:00+00:00"


def test_merge_host_history_prunes_by_age():
    old = {
        "t": "2026-10-09T10:00:00+00:00",
        "cpu": 1.0,
        "ram": 1.0,
        "disk": 1.0,
        "temp": 30.0,
        "dkr": None,
    }
    recent = {
        "t": "2026-10-10T11:55:00+00:00",
        "cpu": 2.0,
        "ram": 2.0,
        "disk": 2.0,
        "temp": 40.0,
        "dkr": None,
    }
    stats = {
        "reported_at": "2026-10-10T12:00:00+00:00",
        "cpu": {"percent": 3.0},
        "ram": {"percent": 3.0},
        "disk": {"percent": 3.0},
        "temperature": {"celsius": 42.0},
        "docker": {},
    }
    merged = merge_host_history(
        {"history": [old, recent]},
        stats,
        max_points=100,
        max_age_seconds=3600,
    )
    assert len(merged) == 2
    assert merged[0]["t"] == recent["t"]
    assert merged[-1]["temp"] == 42.0


def test_report_host_stats_builds_history(repo, monkeypatch):
    monkeypatch.setattr("retail.host_stats.HOST_IP", "192.168.1.90")
    monkeypatch.setattr("retail.host_stats.CYBER_DAY_HOST_IP", "192.168.1.90")
    monkeypatch.setattr("retail.host_stats._LAST_HOST_REPORT_AT", 0.0)
    monkeypatch.setenv("HOST_STATS_TEMP_C", "46.0")
    monkeypatch.setenv(
        "HOST_STATS_FACTS",
        '{"hostname":"precios-cyber-pi","cpu_model":"Cortex-A76","cpu_cores":8,'
        '"cpu_arch":"aarch64","os_pretty_name":"Ubuntu 22.04.5 LTS",'
        '"kernel":"5.10.160","machine_model":"Orange Pi 5"}',
    )
    first = report_host_stats(repo, force=True)
    assert first is not None
    assert isinstance(first.get("history"), list)
    assert len(first["history"]) == 1
    assert first["history"][0]["temp"] == 46.0
    assert first["facts"]["cpu_model"] == "Cortex-A76"
    assert first["facts"]["os_pretty_name"] == "Ubuntu 22.04.5 LTS"
    assert first["hostname"] == "precios-cyber-pi"

    monkeypatch.setattr("retail.host_stats._LAST_HOST_REPORT_AT", 0.0)
    monkeypatch.setenv("HOST_STATS_TEMP_C", "47.5")
    second = report_host_stats(repo, force=True)
    assert second is not None
    assert len(second["history"]) == 2
    assert second["history"][-1]["temp"] == 47.5

    payload = admin_hosts_payload(repo)
    by_id = {h["id"]: h for h in payload["hosts"]}
    assert len(by_id["orange_pi"]["history"]) == 2
    assert by_id["orange_pi"]["facts"]["machine_model"] == "Orange Pi 5"
    assert payload["history"]["max_points"] >= 24


def test_host_alerts_disk_ram_docker_stale():
    online = {
        "online": True,
        "disk": {"percent": 82, "free_bytes": 20 * 1024**3},
        "ram": {"percent": 91},
        "temperature": {"celsius": 72, "source": "cpu-thermal"},
        "docker": {"reclaimable_bytes": 25 * 1000**3},
    }
    codes = {a["code"] for a in host_alerts(online)}
    assert "disk_warn" in codes
    assert "ram_warn" in codes
    assert "temp_warn" in codes
    assert "docker_reclaim" in codes

    hot = {
        "online": True,
        "disk": {"percent": 95, "free_bytes": 5 * 1024**3},
        "ram": {},
        "temperature": {"celsius": 90, "source": "x86_pkg_temp"},
        "docker": {},
    }
    codes_hot = {a["code"] for a in host_alerts(hot)}
    assert "disk_hot" in codes_hot
    assert "temp_hot" in codes_hot

    stale = {"online": False, "reported_at": "2020-01-01T00:00:00+00:00"}
    assert host_alerts(stale)[0]["code"] == "stale"


def test_admin_hosts_payload_fixed_three_and_stale(repo):
    from datetime import datetime, timezone

    now_iso = datetime.now(timezone.utc).isoformat()
    fresh = {
        "hostname": "precios-cyber-pi",
        "ip": "192.168.1.90",
        "reported_at": now_iso,
        "uptime_seconds": 3600,
        "cpu": {"percent": 12.0, "cores": 4, "load1": 0.5, "load5": 0.4, "load15": 0.3},
        "ram": {"used_bytes": 1, "free_bytes": 2, "total_bytes": 3, "percent": 33.0},
        "disk": {"path": "/", "used_bytes": 1, "free_bytes": 2, "total_bytes": 3, "percent": 10.0},
        "temperature": {"celsius": 48.5, "source": "cpu-thermal"},
        "docker": {
            "images_bytes": 1_000_000_000,
            "images_reclaimable_bytes": 100_000_000,
            "reclaimable_bytes": 100_000_000,
        },
        "facts": {
            "hostname": "precios-cyber-pi",
            "cpu_model": "Cortex-A76",
            "cpu_cores": 8,
            "cpu_arch": "aarch64",
            "mem_total_bytes": 8 * 1024**3,
            "disk_total_bytes": 128 * 1024**3,
            "os_pretty_name": "Ubuntu 22.04.5 LTS",
            "kernel": "5.10.160-rockchip",
            "uptime_seconds": 3600.0,
            "machine_model": "Orange Pi 5",
        },
        "history": [
            {"t": "2026-10-10T11:58:00+00:00", "cpu": 10.0, "ram": 30.0, "disk": 10.0, "temp": 46.0, "dkr": None},
            {"t": now_iso, "cpu": 12.0, "ram": 33.0, "disk": 10.0, "temp": 48.5, "dkr": 100_000_000},
        ],
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
    assert by_id["orange_pi"]["temperature"]["celsius"] == 48.5
    assert by_id["orange_pi"]["temperature"]["source"] == "cpu-thermal"
    assert by_id["orange_pi"]["docker"]["images_bytes"] == 1_000_000_000
    assert by_id["orange_pi"]["role"] == "Cyber Day scrape"
    assert by_id["orange_pi"]["facts"]["cpu_model"] == "Cortex-A76"
    assert by_id["orange_pi"]["facts"]["os_pretty_name"] == "Ubuntu 22.04.5 LTS"
    assert by_id["orange_pi"]["facts"]["machine_model"] == "Orange Pi 5"
    assert len(by_id["orange_pi"]["history"]) == 2
    assert by_id["orange_pi"]["history"][-1]["temp"] == 48.5
    assert by_id["soyo"]["temperature"] is None
    assert by_id["soyo"]["facts"] is None
    assert by_id["soyo"]["history"] == []
    assert any(a["host_id"] == "bmax" for a in payload["alerts"])
    assert payload["thresholds"]["disk_warn"] == 80
    assert payload["thresholds"]["temp_warn"] == 70
    assert payload["thresholds"]["temp_hot"] == 85
    assert payload["history"]["max_points"] == 1440
    assert payload["history"]["max_age_seconds"] == 24 * 3600


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
    assert "hosts-trends" in html
    assert "hosts-detail-modal" in html
    assert "/api/admin/hosts" in js
    assert "BMAX" in html and "soyo" in html and "Orange Pi" in html
    assert "gaugeSvg" in js
    assert "tempGaugePercent" in js
    assert 'metricBlock("temp"' in js or "kind === \"temp\"" in js
    assert "host.temperature" in js
    assert "temp_warn" in js and "temp_hot" in js
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
    assert "temperatura" in html.lower()
    assert "sparklineSvg" in js
    assert "multiHostChart" in js
    assert "renderTrends" in js
    assert "hostSparklines" in js
    assert "historySeries" in js
    assert "openHostDetail" in js
    assert "FACT_ROWS" in js
    assert "stopPropagation" in js
    assert "host.facts" in js
    assert (root / "hosts" / "bmax.png").is_file()
    assert (root / "hosts" / "soyo.jpg").is_file()
    assert (root / "hosts" / "orange-pi.jpg").is_file()
    assert "load1" in js and "load5" in js
    assert "docker" in js.lower()
    css = (root / "styles.css").read_text(encoding="utf-8")
    assert "hosts-trends" in css
    assert "hosts-spark" in css
    assert "hosts-chart-series" in css or "hosts-chart-svg" in css
    assert "hosts-facts-table" in css
    assert "hosts-detail-modal" in css
    report_sh = Path("scripts/host-stats-report.sh").read_text(encoding="utf-8")
    assert "host_temp_env" in report_sh
    assert "HOST_STATS_TEMP_C" in report_sh
    assert "host_facts_env" in report_sh
    assert "HOST_STATS_FACTS_B64" in report_sh
    prices = (root / "prices.js").read_text(encoding="utf-8")
    assert 'href="/hosts"' in prices or '"/hosts"' in prices
    assert "Hosts" in prices
