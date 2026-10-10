"""Matriz lista de compra × tiendas (catálogo Mongo, sin scrape síncrono)."""
from datetime import datetime, timedelta, timezone

from retail.quotes import QuoteLine, parse_csv_quote
from retail.relevance import equivalent_tokens
from retail.search_cache import rewrite_search_query
from retail.shopping_list import (
    EMPTY_CELL_LABEL,
    PRICE_MAX_AGE_HOURS,
    _empty_cell,
    _line_search_query,
    available_store_groups,
    best_match_for_store,
    list_candidate_for,
    matrix_export_csv,
    refresh_quote_prices,
    shopping_matrix_report,
)

NOW = datetime(2026, 10, 5, 16, tzinfo=timezone.utc)


def _doc(store, product_id, name, price, **extra):
    return {
        "store": store,
        "product_id": product_id,
        "sku_id": product_id,
        "name": name,
        "brand": extra.pop("brand", ""),
        "condition": "new",
        "price": price,
        "price_all_payment": price,
        "stock": extra.pop("stock", 20),
        "currency": "CLP",
        "updated_at": NOW,
        **extra,
    }


def test_shopping_list_csv_allows_optional_price_and_quantity():
    lines = parse_csv_quote(
        "nombre;cantidad;marca\n"
        "Azúcar granulada 1 kg;2;Iansa\n"
        "Café molido 500 g;;Juan Valdez\n"
        "Papel higiénico 12 un;1;\n"
    )
    assert len(lines) == 3
    assert lines[0].unit_price is None
    assert lines[0].quantity == 2
    assert lines[1].quantity == 1  # default
    assert lines[2].name.startswith("Papel")


def test_shopping_list_csv_parses_combined_quantity_unit_comma():
    lines = parse_csv_quote("nombre,cantidad,marca\nazúcar,1 kg,lanza\n")
    assert lines[0].quantity == 1
    assert lines[0].unit == "kg"
    assert lines[0].brand == "lanza"


def test_matrix_three_items_three_stores_and_basket_total():
    quote = {
        "mode": "shopping_list",
        "store_group": "supermercados",
        "title": "Super",
        "tax_included": True,
        "items": [
            {"name": "Azúcar granulada 1 kg", "quantity": 1, "unit": "unidad", "brand": "", "gtin": "", "condition": "new"},
            {"name": "Café molido 500 g", "quantity": 2, "unit": "unidad", "brand": "", "gtin": "", "condition": "new"},
            {"name": "Papel higiénico 12 un", "quantity": 1, "unit": "unidad", "brand": "", "gtin": "", "condition": "new"},
        ],
    }
    stores = ["lider", "unimarc", "tottus"]
    documents = {
        ("lider", "az"): _doc("lider", "az", "Azúcar granulada 1 kg", 1290),
        ("unimarc", "az"): _doc("unimarc", "az", "Azúcar granulada 1 kg", 1190),
        ("tottus", "az"): _doc("tottus", "az", "Azúcar granulada 1 kg", 1350),
        ("lider", "cf"): _doc("lider", "cf", "Café molido 500 g", 4500),
        ("unimarc", "cf"): _doc("unimarc", "cf", "Café molido 500 g", 4200),
        # tottus sin café
        ("lider", "ph"): _doc("lider", "ph", "Papel higiénico 12 un", 5990),
        ("unimarc", "ph"): _doc("unimarc", "ph", "Papel higiénico 12 un", 6200),
        ("tottus", "ph"): _doc("tottus", "ph", "Papel higiénico 12 un", 5800),
    }
    store_matches = {
        "0": {
            "lider": {"store": "lider", "product_id": "az", "confirmed": False},
            "unimarc": {"store": "unimarc", "product_id": "az", "confirmed": False},
            "tottus": {"store": "tottus", "product_id": "az", "confirmed": False},
        },
        "1": {
            "lider": {"store": "lider", "product_id": "cf", "confirmed": False},
            "unimarc": {"store": "unimarc", "product_id": "cf", "confirmed": False},
        },
        "2": {
            "lider": {"store": "lider", "product_id": "ph", "confirmed": False},
            "unimarc": {"store": "unimarc", "product_id": "ph", "confirmed": False},
            "tottus": {"store": "tottus", "product_id": "ph", "confirmed": False},
        },
    }
    report = shopping_matrix_report(quote, store_matches, documents, stores=stores, now=NOW)
    assert report["stores"] == stores
    assert len(report["rows"]) == 3
    assert report["rows"][0]["cells"]["unimarc"]["price"] == 1190
    assert report["rows"][1]["cells"]["tottus"]["matched"] is False
    assert report["rows"][1]["cells"]["tottus"]["label"] == EMPTY_CELL_LABEL
    # Café ×2 en unimarc = 8400; azúcar 1190; papel 6200 → 15790
    unimarc = next(row for row in report["summary"]["basket"] if row["store"] == "unimarc")
    assert unimarc["matched_items"] == 3
    assert unimarc["subtotal"] == 1190 + 8400 + 6200
    assert unimarc["complete"] is True
    # Tottus incompleta (falta café)
    tottus = next(row for row in report["summary"]["basket"] if row["store"] == "tottus")
    assert tottus["complete"] is False
    assert tottus["missing_items"] == 1
    assert "Café" in tottus["missing_names"][0]
    # Mejor canasta completa: unimarc 15790 vs lider 1290+9000+5990=16280
    assert report["summary"]["best_store"] == "unimarc"
    assert report["summary"]["best_store_subtotal"] == 15790
    assert report["summary"]["best_store_complete"] is True
    # Mejor precio por ítem
    assert report["rows"][0]["best_store"] == "unimarc"
    assert report["rows"][0]["best_price"] == 1190
    assert report["rows"][1]["best_store"] == "unimarc"
    assert report["rows"][2]["best_store"] == "tottus"
    assert report["rows"][2]["best_price"] == 5800

    csv_text = matrix_export_csv(report)
    assert "Azúcar granulada 1 kg" in csv_text
    assert "unimarc CLP" in csv_text
    assert EMPTY_CELL_LABEL in csv_text
    assert "Mejor tienda canasta" in csv_text
    assert "unimarc" in csv_text
    assert "Fecha precio mejor" in csv_text
    assert "Stale mejor" in csv_text
    assert "unimarc fecha precio" in csv_text
    assert "unimarc stale" in csv_text
    assert "unimarc usable" in csv_text
    assert "unimarc confirmada" in csv_text
    assert "unimarc estado" in csv_text
    assert "Sin despacho" in csv_text
    assert "Celdas stale" in csv_text
    assert "Generado" in csv_text
    assert "Celdas buscando" in csv_text
    assert str(PRICE_MAX_AGE_HOURS) in csv_text
    assert report["summary"]["shipping_note"]
    assert report["summary"]["price_max_age_hours"] == PRICE_MAX_AGE_HOURS


def test_matrix_empty_when_no_identity_match():
    quote = {
        "mode": "shopping_list",
        "store_group": "supermercados",
        "tax_included": True,
        "items": [
            {"name": "Azúcar granulada 1 kg", "quantity": 1, "unit": "unidad", "brand": "", "gtin": "", "condition": "new"},
        ],
    }
    documents = {
        ("lider", "x"): _doc("lider", "x", "Detergente líquido 3 L", 4990),
    }
    store_matches = {"0": {"lider": {"store": "lider", "product_id": "x"}}}
    report = shopping_matrix_report(quote, store_matches, documents, stores=["lider"], now=NOW)
    assert report["rows"][0]["cells"]["lider"]["matched"] is False
    assert report["summary"]["matched_cells"] == 0


def test_quote_line_optional_unit_price_still_validates_name():
    line = QuoteLine(name="Café instantáneo 100 g")
    assert line.unit_price is None
    assert line.quantity == 1


def test_query_subset_rejects_incompatible_pack_size():
    """1.5 kg de la lista no debe matchear un SKU de 1 kg (ni al revés)."""
    line = QuoteLine(name="Azúcar granulada 1.5 kg", brand="Iansa")
    one_kg = _doc(
        "tottus",
        "az-1kg",
        "Azúcar Granulada 1 Kg",
        1490,
        brand="Iansa",
        availability="disponible",
    )
    one_half = _doc(
        "cugat",
        "az-15",
        "Azúcar Granulada 1.5 Kg",
        1790,
        brand="Iansa",
        availability="disponible",
    )
    assert list_candidate_for(line, one_kg, now=NOW) is None
    hit = list_candidate_for(line, one_half, now=NOW)
    assert hit is not None
    assert hit["product_id"] == "az-15"
    if hit.get("match_method") == "query_subset":
        assert float(hit.get("rank_boost") or 0) >= 0.4
    best = best_match_for_store(line, [one_kg, one_half], "cugat", now=NOW)
    assert best is not None and best["product_id"] == "az-15"
    # Lista sin envase sigue pudiendo sugerir 400 g.
    bare = QuoteLine(name="azúcar")
    sugar400 = _doc("alvi", "az-400", "Azúcar granulada Iansa, 400 g", 890, brand="Iansa", availability="disponible")
    assert list_candidate_for(bare, sugar400, now=NOW) is not None


def test_short_azucar_matches_iansa_sugar_via_query_subset():
    """Una sola palabra genérica debe sugerir azúcares del catálogo (no exige identidad 80%)."""
    line = QuoteLine(name="azúcar")
    sugar = _doc(
        "alvi",
        "sugar-1",
        "Azúcar granulada Iansa, 400 g",
        890,
        brand="Iansa",
        availability="disponible",
    )
    gum = _doc(
        "alvi",
        "gum-1",
        "Chicle energy con cafeína sin azúcar",
        490,
        brand="Trident",
        availability="disponible",
    )
    detergent = _doc("alvi", "det-1", "Detergente líquido 3 L", 4990, brand="Skip", availability="disponible")
    hit = list_candidate_for(line, sugar, now=NOW)
    miss = list_candidate_for(line, detergent, now=NOW)
    negated = list_candidate_for(line, gum, now=NOW)
    assert hit is not None
    assert hit["match_method"] == "query_subset"
    assert hit["confidence"] >= 0.7
    assert "Iansa" in hit["name"]
    assert miss is None
    assert negated is None

    line_alias = QuoteLine(name="azúcar ianza")
    alias_hit = list_candidate_for(line_alias, sugar, now=NOW)
    assert alias_hit is not None
    assert "iansa" in (alias_hit.get("name") or "").casefold() or alias_hit.get("match_method") in {
        "query_subset",
        "identity",
        "hybrid_text",
    }

    best = best_match_for_store(line, [gum, sugar, detergent], "alvi", now=NOW)
    assert best is not None
    assert best["product_id"] == "sugar-1"

    # Case / acentos
    for raw in ("azucar", "AZÚCAR", "Azúcar"):
        assert list_candidate_for(QuoteLine(name=raw), sugar, now=NOW) is not None


def test_stale_candidate_flags_price_outside_window():
    line = QuoteLine(name="Azúcar granulada 1 kg")
    old = NOW - timedelta(hours=PRICE_MAX_AGE_HOURS + 2)
    fresh_doc = _doc("lider", "az", "Azúcar granulada 1 kg", 1290)
    stale_doc = _doc("lider", "az", "Azúcar granulada 1 kg", 1290, updated_at=old)
    fresh = list_candidate_for(line, fresh_doc, now=NOW)
    stale = list_candidate_for(line, stale_doc, now=NOW)
    assert fresh is not None and fresh["stale"] is False and fresh["usable"] is True
    assert stale is not None and stale["stale"] is True
    assert stale["usable"] is False
    assert stale["price_age_hours"] and stale["price_age_hours"] > PRICE_MAX_AGE_HOURS
    assert "fecha reciente" in " ".join(stale["issues"]).lower()

    quote = {
        "mode": "shopping_list",
        "store_group": "supermercados",
        "tax_included": True,
        "items": [
            {"name": "Azúcar granulada 1 kg", "quantity": 1, "unit": "unidad", "brand": "", "gtin": "", "condition": "new"},
        ],
    }
    store_matches = {"0": {"lider": {"store": "lider", "product_id": "az"}}}
    report = shopping_matrix_report(
        quote, store_matches, {("lider", "az"): stale_doc}, stores=["lider"], now=NOW
    )
    cell = report["rows"][0]["cells"]["lider"]
    assert cell["matched"] is True
    assert cell["stale"] is True
    assert cell["usable"] is False
    assert report["summary"]["stale_cells"] == 1
    assert cell["match_reason"]
    basket = next(row for row in report["summary"]["basket"] if row["store"] == "lider")
    assert basket["matched_items"] == 1
    assert basket["usable_items"] == 0
    assert basket["subtotal"] is None
    assert basket["complete"] is False
    assert report["summary"]["best_store"] is None
    assert report["summary"]["complete"] is False


def test_empty_cell_hints_distinguish_no_match_vs_no_catalog():
    no_match = _empty_cell(reason="no_match")
    no_catalog = _empty_cell(reason="no_catalog")
    assert "EAN" in no_match["label"] or "corto" in no_match["label"]
    assert "catálogo" in no_catalog["label"]
    assert no_match["empty_reason"] == "no_match"
    assert no_catalog["empty_reason"] == "no_catalog"


def test_pack_noise_stripped_from_list_search_query():
    cases = [
        ("Leche entera x 6 un", "leche"),
        ("Yogurt pack de 12", "yogurt"),
        ("Huevos 12 un por pack", "huevo"),
    ]
    for name, keep in cases:
        query = _line_search_query(QuoteLine(name=name)).casefold()
        assert keep in query
        assert "x 6" not in query
        assert "pack" not in query
        assert "12 un" not in query


def test_grocery_aliases_cover_common_list_tokens():
    assert "iansa" in equivalent_tokens("ianza")
    assert "yogurt" in equivalent_tokens("yogur")
    assert "fideo" in equivalent_tokens("pasta") or "fideos" in equivalent_tokens("pasta")
    assert "iansa" in rewrite_search_query("azúcar ianza").casefold()


def test_refresh_quote_prices_boosts_matched_skus_with_catalog_id():
    updates = []

    class Priorities:
        def update_one(self, query, updates_doc, upsert=False):
            updates.append((query, updates_doc, upsert))
            return None

    repo = type("Repo", (), {
        "scrape_priorities": Priorities(),
        "product_detail": staticmethod(
            lambda store, product_id: {
                "store": store,
                "product_id": product_id,
                "catalog_id": f"cat-{store}-{product_id}",
            }
        ),
        "watches": None,
        "price_alerts": None,
    })()
    quote = {
        "mode": "shopping_list",
        "store_matches": {
            "0": {
                "lider": {"store": "lider", "product_id": "az"},
                "unimarc": {"store": "unimarc", "product_id": "az"},
            }
        },
    }
    result = refresh_quote_prices(repo, quote)
    assert result["targets"] == 2
    assert result["boosted"] == 2
    assert "prioridad" in result["message"].casefold() or "sku" in result["message"].casefold()
    assert len(updates) == 2


def test_resolve_list_stores_expands_selected_categories(monkeypatch):
    from retail.shopping_list import resolve_list_stores

    monkeypatch.setattr(
        "retail.shopping_list.stores_for_group",
        lambda group, repo=None: {
            "supermercados": ["lider", "tottus"],
            "retail": ["falabella", "paris"],
        }.get(group, []),
    )
    stores = resolve_list_stores({"store_groups": ["supermercados", "retail"]})
    assert stores == ["lider", "tottus", "falabella", "paris"]
    # store_ids legacy sigue funcionando si no hay store_groups
    assert resolve_list_stores({"store_group": "supermercados", "store_ids": ["lider"]}) == ["lider"]


def test_available_store_groups_include_title_and_logo(monkeypatch):
    monkeypatch.setattr(
        "retail.shopping_list.list_store_categories",
        lambda repo=None: [{"id": "retail", "title": "Retail"}],
    )
    monkeypatch.setattr(
        "retail.shopping_list.stores_for_group",
        lambda group_id, repo=None: ["falabella", "elite_professional"],
    )
    groups = available_store_groups()
    assert groups[0]["title"] == "Retail"
    assert groups[0]["store_ids"] == ["falabella", "elite_professional"]
    by_id = {row["id"]: row for row in groups[0]["stores"]}
    assert by_id["falabella"]["title"] == "Falabella"
    assert by_id["falabella"]["logo"] == "/static/logos/falabella.png"
    assert by_id["elite_professional"]["title"] == "Elite Professional"
    assert by_id["elite_professional"]["logo"] == "/static/logos/_store.svg"
