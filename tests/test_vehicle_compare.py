from retail.compare import compare_code, identity_match_confidence
from retail.models import Product


def _vehicle(store: str, ident: str, *, condition: str, year: str = "2024", version: str = "Sport") -> Product:
    return Product(
        product_id=ident,
        sku_id=ident,
        name=f"{year} Toyota Yaris {version}",
        brand="Toyota",
        store=store,
        price=10000000,
        condition=condition,
        specifications={
            "vehicle_type": "car",
            "year": year,
            "model": "Yaris",
            "version": version,
        },
    )


def test_autos_usados_son_avisos_unicos_aunque_nombre_coincida():
    one = _vehicle("chileautos", "uno", condition="used")
    two = _vehicle("autocosmos", "dos", condition="used")
    assert compare_code(one) != compare_code(two)
    assert identity_match_confidence(one, two) == (0.0, "used_vehicle_unique")


def test_auto_nuevo_exige_mismo_ano_y_version():
    one = _vehicle("chileautos", "uno", condition="new")
    same = _vehicle("autocosmos", "dos", condition="new")
    other_year = _vehicle("autocosmos", "tres", condition="new", year="2023")
    other_version = _vehicle("autocosmos", "cuatro", condition="new", version="XLI")
    assert compare_code(one) == compare_code(same)
    assert identity_match_confidence(one, other_year)[0] == 0.0
    assert identity_match_confidence(one, other_version)[0] == 0.0
