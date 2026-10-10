"""Normalización de nombres visibles de tienda (sufijo Chile)."""

from retail.store_display import (
    clean_store_display_name,
    display_store,
    public_store_label,
    store_logo_static_url,
)


def test_clean_store_display_name_strips_chile_suffix():
    assert clean_store_display_name("Easy Chile") == "Easy"
    assert clean_store_display_name("Paris Chile") == "Paris"
    assert clean_store_display_name("LIDER CHILE") == "LIDER"
    assert clean_store_display_name("Mercado Libre Chile") == "Mercado Libre"
    assert clean_store_display_name("  Easy   Chile  ") == "Easy"


def test_clean_store_display_name_keeps_legitimate_chile_brands():
    assert clean_store_display_name("Chileautos") == "Chileautos"
    assert clean_store_display_name("Chile Perfume") == "Chile Perfume"
    assert clean_store_display_name("Feria Chilena del Libro") == "Feria Chilena del Libro"
    assert clean_store_display_name("Falabella") == "Falabella"
    assert clean_store_display_name("") == ""


def test_public_store_label_and_display_store_drop_chile():
    assert public_store_label("easy", {"easy": "Easy Chile"}) == "Easy"
    assert display_store({"store": "easy", "store_title": "Easy Chile"}) == ("easy", "Easy")
    assert display_store({"store": "paris", "store_title": "Paris Chile"}) == ("paris", "Paris")
    # Ids/slugs internos no se renombran.
    assert display_store({"store": "easy", "store_title": "Easy Chile"})[0] == "easy"


def test_store_logo_static_url_uses_existing_assets_only():
    assert store_logo_static_url("falabella") == "/static/logos/falabella.png"
    assert store_logo_static_url("lider") == "/static/logos/lider.svg"
    # Sin asset inventado: genérico (la UI muestra inicial).
    assert store_logo_static_url("elite_professional") == "/static/logos/_store.svg"
    assert store_logo_static_url("knasta") == "/static/logos/_store.svg"
