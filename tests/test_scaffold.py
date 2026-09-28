from retail.registry import list_stores
from retail.scaffold import class_name_for, normalize_store_id, render_store_module


def test_normalize_and_class_name():
    assert normalize_store_id("Mercado-Libre") == "mercado_libre"
    assert class_name_for("mercado_libre") == "MercadoLibreStore"


def test_render_custom_source_uses_new_paths():
    code = render_store_module("acme", "Acme Chile", "www.acme.cl")
    assert 'id="acme"' in code
    assert "from retail.base import StoreClient" in code
    assert "from retail.http import HttpError" in code
    assert "class AcmeStore(StoreClient)" in code
    assert 'store="acme"' in code
    assert "retail/sources/acme.py" in code
    assert 'platform="custom"' in code


def test_render_vtex_source_uses_platform_factory():
    code = render_store_module("acme", "Acme Chile", "www.acme.cl", platform="vtex", brand="Acme")
    assert "from retail.platforms.vtex import make_vtex_store" in code
    assert 'store_id="acme"' in code
    assert "default_brand='Acme'" in code


def test_sources_are_auto_discovered():
    ids = {spec.id for spec in list_stores()}
    assert {"falabella", "nike", "weplay", "doite"}.issubset(ids)
    assert next(spec.platform for spec in list_stores() if spec.id == "nike") == "vtex"
    assert next(spec.platform for spec in list_stores() if spec.id == "doite") == "shopify"
    assert next(spec.platform for spec in list_stores() if spec.id == "weplay") == "magento"
