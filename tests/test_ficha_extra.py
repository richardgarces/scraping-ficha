from retail.ficha_extra import (
    description_of,
    pick_related,
    related_score,
    specifications_of,
)


def test_specs_from_dict_string_and_attributes():
    assert specifications_of({"specifications": {"Peso": "1 kg", "Ancho": ""}}) == {"Peso": "1 kg"}
    assert specifications_of({"specifications": "Marca: Nike | Talla: 42"}) == {"Marca": "Nike", "Talla": "42"}
    assert specifications_of({"attributes": [{"name": "Compatibilidad", "value": "USB-C"}]}) == {
        "Compatibilidad": "USB-C"
    }


def test_specs_parse_embedded_json_without_showing_brackets():
    raw = '[{"label":"Tipo de producto","value":"Tapones de oído","unit":""},{"label":"Categoría","value":"Ferretería/Seguridad"}]'
    expected = {
        "Tipo de producto": "Tapones de oído",
        "Categoría": "Ferretería/Seguridad",
    }
    assert specifications_of({"specifications": raw}) == expected
    assert specifications_of({"specifications": {"Specs": raw}}) == expected


def test_description_strips_html():
    assert description_of({"description": "<p>Texto <b>largo</b></p>"}) == "Texto largo"
    assert description_of({}) == ""


def test_related_skips_current_and_same_compare_code():
    seed = {
        "store": "falabella",
        "product_id": "1",
        "name": "Zapatilla Nike Air Max negra",
        "brand": "Nike",
        "category": "Zapatillas",
        "compare_code": "air-max",
    }
    same = {**seed}
    twin = {**seed, "store": "paris", "product_id": "9"}
    other = {
        "store": "ripley",
        "product_id": "2",
        "name": "Zapatilla Nike Revolution",
        "brand": "Nike",
        "category": "Zapatillas",
        "price": 39990,
    }
    noise = {
        "store": "lider",
        "product_id": "3",
        "name": "Arroz grado 2",
        "brand": "Tucapel",
        "category": "Abarrotes",
        "price": 1500,
    }
    assert related_score(seed, same) is None
    assert related_score(seed, twin) is None
    assert related_score(seed, noise) is None
    picked = pick_related(seed, [same, twin, noise, other])
    assert [item["product_id"] for item in picked] == ["2"]


def test_related_caps_and_prefers_same_group():
    seed = {
        "store": "easy",
        "product_id": "a",
        "name": "Taladro percutor 500w",
        "brand": "Bosch",
        "category_id": "taladros",
    }
    rows = [
        {
            "store": "sodimac",
            "product_id": f"p{index}",
            "name": f"Taladro percutor modelo {index}",
            "brand": "Bosch",
            "category_id": "taladros",
            "price": 10000 + index,
        }
        for index in range(20)
    ]
    picked = pick_related(seed, rows)
    assert len(picked) == 12
    assert all(item["product_id"] != "a" for item in picked)
