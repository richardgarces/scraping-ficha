import json
import shutil
import subprocess
from pathlib import Path

import pytest

from retail.pricing import price_observations


def test_price_observations_orders_deduplicates_and_keeps_latest_daily_offer():
    rows = price_observations(
        [
            {"price": "120000", "price_normal": "140000", "price_basis": "all_payment", "scraped_at": "2026-10-02T18:00:00Z"},
            {"price": 100000, "price_normal": None, "price_basis": "all_payment", "scraped_at": "2026-10-02T22:00:00Z"},
            {"price": 90000, "price_normal": 90000, "price_basis": "all_payment", "scraped_at": "2026-10-01T18:00:00Z"},
            {"price": 50000, "scraped_at": "2026-09-30T18:00:00Z"},
        ]
    )

    assert [(row["day"], row["offer"], row["normal"]) for row in rows] == [
        ("2026-10-01", 90000, 90000),
        ("2026-10-02", 100000, 140000),
    ]
    assert rows[-1]["saving"] == 40000


def test_price_observations_does_not_fill_missing_days_or_normal_prices():
    rows = price_observations(
        [
            {"price": 100000, "scraped_at": "2026-10-01T18:00:00Z"},
            {"price": 150000, "price_normal": 150000, "scraped_at": "2026-10-04T18:00:00Z"},
        ]
    )

    assert [row["day"] for row in rows] == ["2026-10-01", "2026-10-04"]
    assert rows[0]["normal"] is None
    assert rows[1]["saving"] == 0


def test_price_observations_keeps_legitimate_outlier_and_current_value():
    rows = price_observations(
        [
            {"price": 100000, "price_normal": 100000, "scraped_at": "2026-10-01T18:00:00Z"},
            {"price": 500000, "price_normal": 500000, "scraped_at": "2026-10-02T18:00:00Z"},
        ],
        current_offer=90000,
        current_normal=90000,
        current_at="2026-10-04T23:00:00Z",
    )

    assert [row["offer"] for row in rows] == [100000, 500000, 90000]
    assert rows[-1]["day"] == "2026-10-04"


def test_frontend_history_helpers_cover_ranges_equal_series_and_statistics():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js no está instalado")
    helper = Path("retail/web/static/price-history.js").resolve()
    script = f"""
      const h = require({json.dumps(str(helper))});
      const rows = [
        {{day:'2026-09-20', offer:100000, normal:100000}},
        {{day:'2026-09-29', offer:120000, normal:null}},
        {{day:'2026-10-02', offer:500000, normal:500000}},
        {{day:'2026-10-04', offer:90000, normal:100000}},
      ];
      const ranged = h.filter(rows, 7, '2026-10-04');
      const result = {{
        days: ranged.map(x => x.day),
        stats: h.stats(ranged.map(x => x.offer)),
        meaningful: h.hasMeaningfulNormal(ranged),
        equal: h.hasMeaningfulNormal([{{day:'2026-10-04', offer:90000, normal:90000}}]),
      }};
      process.stdout.write(JSON.stringify(result));
    """
    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)

    assert data["days"] == ["2026-09-29", "2026-10-02", "2026-10-04"]
    assert data["stats"] == {
        "current": 90000,
        "min": 90000,
        "max": 500000,
        "average": 236667,
        "first": 120000,
        "count": 3,
    }
    assert data["meaningful"] is True
    assert data["equal"] is False
