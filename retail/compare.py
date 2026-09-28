from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from retail.commercial import condition_group, conditions_compatible
from retail.commercial import landed_price, shipping_comparable
from retail.models import Product

_STORAGE_RE = re.compile(r"\b(\d{2,4})\s*(tb|gb|g)\b")
_RAM_PATTERNS = (
    re.compile(r"\b(?:ram|memoria\s+ram)\s*(?:de\s*)?(\d{1,3})\s*(?:gb|g)\b"),
    re.compile(r"\b(\d{1,3})\s*(?:gb|g)\s*(?:de\s*)?(?:ram|memoria\s+ram)\b"),
)
_MODEL_RE = re.compile(r"\b[a-z]{1,10}\d{1,4}[a-z0-9]{0,10}\b")
# Expresiones comerciales como "2 en 1" o "4 en 1" no son modelos. Al
# compactarse el texto, el fragmento ``en1`` cumplía por accidente el patrón
# de modelo y podía juntar productos totalmente distintos de una misma marca.
_GENERIC_MODEL_TOKENS = {"en1", "x1", "unidad1", "un1"}
_BUNDLE_RE = re.compile(r"\b(?:kit|bundle|combo|incluye|con regalo)\b")
_STOP = {
    "con",
    "para",
    "the",
    "and",
    "celular",
    "celulares",
    "telefono",
    "smartphone",
    "smartphones",
    "notebook",
    "notebooks",
    "laptop",
    "portatil",
    "juego",
    "set",
    "pack",
    "nuevo",
    "oferta",
    "reacondicionado",
    "dual",
    "sim",
    "ram",
    "piezas",
    "exterior",
    "interior",
    "galaxy",
    "iphone",
    "5g",
    "4g",
    "3g",
    "en1",
}


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    # "S25+" es otro teléfono que "S25": el signo al final del modelo se
    # conserva como palabra. En "12+512G" separa dos cifras y sigue siendo aire.
    text = re.sub(r"\+(?=\s|$)", "plus", text)
    text = text.replace("+", " ").replace("-", " ").replace("/", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


def _alias_models(text: str) -> str:
    """Pega al modelo la palabra que marca la gama.

    "S25 Ultra" es otro teléfono que "S25", pero suelta la palabra se pierde
    entre el relleno del título. Ripley además la antepone: "Galaxy Ultra S25".
    """
    text = re.sub(r"\bs(\d{2})\s*(ultra|plus|fe)\b", r"s\1\2", text)
    text = re.sub(r"\b(ultra|plus|fe)\s+s(\d{2})\b", r"s\2\1", text)
    text = re.sub(r"\biphone\s*(\d+)", r"iphone\1", text)
    return text


_INCH_RE = re.compile(r"(\d{2,3})\s*(?:\"|”|″|''|´´|pulgadas?|pulg\.?)")
_BARE_NUMBER_RE = re.compile(r"\b(\d{2,3})\b")
_SCREEN_WORDS = ("tv", "televisor", "monitor", "notebook", "tablet", "smarttv")
_INCH_RANGE = (10, 120)


def screen_size(text: str) -> str | None:
    """Pulgadas de la pantalla, que distinguen productos por lo demás idénticos.

    Sin esto un U8000H de 43" y uno de 65" comparten huella y la app los compara
    entre sí: la "diferencia de precio entre tiendas" pasa a ser la diferencia
    de tamaño. Tottus escribe "Smart Tv 43 Crystal", sin comillas ni unidad, así
    que el número suelto solo se acepta si el nombre habla de una pantalla.
    """
    match = _INCH_RE.search(text)
    if match:
        value = int(match.group(1))
        return str(value) if _INCH_RANGE[0] <= value <= _INCH_RANGE[1] else None
    words = re.findall(r"[a-z]+", text)
    if not any(word in _SCREEN_WORDS for word in words):
        return None
    for raw in _BARE_NUMBER_RE.findall(text):
        value = int(raw)
        if _INCH_RANGE[0] <= value <= _INCH_RANGE[1]:
            return str(value)
    return None


def _main_storage(tokens: list[str]) -> list[str]:
    parsed: list[tuple[int, str]] = []
    for token in tokens:
        if token.endswith("tb"):
            parsed.append((int(token[:-2]) * 1024, token))
        elif token.endswith("gb"):
            parsed.append((int(token[:-2]), token))
    disks = [item for item in parsed if item[0] >= 64]
    chosen = max(disks, default=None) or max(parsed, default=None)
    return [chosen[1]] if chosen else []


def _gtin_checksum_ok(digits: str) -> bool:
    """Último dígito de un GTIN: suma ponderada 3-1 desde la derecha."""
    values = [int(char) for char in digits]
    total = sum(value * (3 if (len(values) - 1 - index) % 2 else 1) for index, value in enumerate(values[:-1]))
    return (10 - total % 10) % 10 == values[-1]


# GS1 reserva estos prefijos para códigos que cada comercio se inventa puertas
# adentro: son válidos como código de barras pero no identifican al producto.
_RESTRICTED_PREFIXES = ("02", "04", "2")
_IDENTIFIER_KEYS = {
    "modelo", "model", "mpn", "manufacturer part number", "part number",
    "codigo fabricante", "codigo del fabricante", "numero de parte",
    "nro de parte", "referencia fabricante",
}
_EAN_KEYS = {"ean", "gtin", "upc", "codigo de barras", "barcode"}


def _spec_key(value: Any) -> str:
    return _fold(str(value or "")).strip(": ")


def _identifier_value(value: Any) -> str | None:
    text = re.sub(r"[^a-z0-9]+", "", _fold(str(value or "")))
    if 3 <= len(text) <= 40 and any(char.isdigit() for char in text):
        return text
    return None


def extract_manufacturer_codes(product: Product) -> tuple[str, ...]:
    found: list[str] = []
    for key, value in (product.specifications or {}).items():
        if _spec_key(key) not in _IDENTIFIER_KEYS:
            continue
        code = _identifier_value(value)
        if code and code not in found:
            found.append(code)
    return tuple(sorted(found))


def normalize_gtin(raw: Any) -> str | None:
    """GTIN a 14 dígitos, o None si no es un código de barras del producto.

    Varias tiendas publican su SKU interno donde iría el código de barras:
    Tottus manda 9 dígitos y Ripley uno que parte en 2000. Tomarlos por EAN
    dejaba al producto solo en su grupo, porque ninguna otra tienda usa ese
    número, y encima dos tiendas distintas pueden reutilizar el mismo.
    """
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) not in {8, 12, 13, 14} or not _gtin_checksum_ok(digits):
        return None
    # Los product_id de Falabella y Sodimac son números de 8 o 9 dígitos, y uno
    # de cada diez pasa el verificador por casualidad: un EAN-8 solo se acepta
    # con el prefijo chileno.
    if len(digits) == 8 and not digits.startswith("780"):
        return None
    padded = digits.zfill(14)
    if len(digits) > 8 and padded[1:].startswith(_RESTRICTED_PREFIXES):
        return None
    return padded


def extract_ean(product: Product) -> str | None:
    # Un código etiquetado explícitamente como EAN/GTIN es más fiable que el
    # SKU numérico de una tienda, que a veces pasa el checksum por casualidad.
    candidates: list[Any] = [
        value for key, value in (product.specifications or {}).items()
        if _spec_key(key) in _EAN_KEYS
    ]
    candidates.extend((product.sku_id, product.product_id))
    for raw in candidates:
        gtin = normalize_gtin(raw)
        if gtin:
            return gtin
    return None


# 16 comprimidos y 400 ml no son lo mismo que 20 comprimidos o 1 L: el precio
# cambia con el envase. Se normalizan para que "1 litro" y "1000 ml" sí calcen.
# Sin cantidad explícita se asume 1 unidad: así "Ozempic" calza con "1 unidad"
# y no con "6 unidades". No tomar dígitos de modelo (iPhone 16) ni pulgadas (TV 65).
_PACK_COUNT_RE = re.compile(
    r"\b(?:x\s*)?(\d{1,4})\s*"
    r"(unidades|unidad|uds|ud|un|u|comprimidos|comprimido|comp|capsulas|capsula|caps|"
    r"cap|tabletas|tableta|tabs|tab|sobres|sobre|ampollas|ampolla|masticables|"
    r"masticable|rollos|rollo|hojas|pares|par)\b"
)
_PACK_MULTI_RE = re.compile(
    r"\b(\d{1,3})\s*x\s*(\d+(?:[.,]\d+)?)\s*(ml|cc|litros|litro|lts|lt|kg|gramos|gramo|grs|gr|mg|g|l)\b"
)
_PACK_SIZE_RE = re.compile(
    r"\b(\d+(?:[.,]\d+)?)\s*(ml|cc|litros|litro|lts|lt|kg|gramos|gramo|grs|gr|mg|g|l)\b"
)
_PACK_PACK_RE = re.compile(
    r"\b(?:(?:multi)?packs?|cajas?|cajitas?|sets?)(?:\s+de)?\s*x?\s*(\d{1,4})\b"
)
_PACK_N_PACK_RE = re.compile(r"\b(\d{1,4})\s*(?:(?:multi)?packs?)\b")
# "x6" / "x 60" al final o suelto; no es "iPhone 16" ni "TV 65".
_PACK_X_RE = re.compile(r"\bx\s*(\d{1,4})\b")
_PACK_UNIT_TOKEN_RE = re.compile(r"^\d+un$|^\d+x\d")
_PACK_WORDS = {
    "unidades",
    "unidad",
    "uds",
    "ud",
    "un",
    "comprimidos",
    "comprimido",
    "comp",
    "capsulas",
    "capsula",
    "caps",
    "cap",
    "tabletas",
    "tableta",
    "tabs",
    "tab",
    "sobres",
    "sobre",
    "ampollas",
    "ampolla",
    "masticables",
    "masticable",
    "rollos",
    "rollo",
    "hojas",
    "pares",
    "par",
    "pack",
    "packs",
    "multipack",
    "multipacks",
    "caja",
    "cajas",
    "cajita",
    "cajitas",
    "set",
    "sets",
    "ml",
    "cc",
    "litro",
    "litros",
    "kg",
    "gramos",
    "gramo",
    "grs",
    "gr",
    "mg",
}


def _norm_qty(amount: str, unit: str) -> str:
    value = float(amount.replace(",", "."))
    key = unit.rstrip("s") if unit not in {"ml", "cc", "mg", "grs"} else unit
    if unit in {"l", "lt", "lts", "litro", "litros"}:
        value, key = value * 1000, "ml"
    elif unit in {"kg"}:
        value, key = value * 1000, "g"
    elif unit in {"cc"}:
        key = "ml"
    elif unit in {"gr", "grs", "gramo", "gramos"}:
        key = "g"
    elif unit == "mg":
        key = "mg"
    elif unit in {"ml"}:
        key = "ml"
    elif unit == "g":
        key = "g"
    number = int(value) if value == int(value) else round(value, 2)
    return f"{number}{key}"


def pack_tokens(text: str) -> tuple[str, ...]:
    """Envase y cantidad: 16 comprimidos, 400 ml, 6 x 100 ml, pack 6, x6.

    Si no hay conteo de unidades (Nun / Nx…), se asume 1un para no mezclar un
    multipack con el mismo producto suelto, y para que omitir "1 unidad" siga
    calzando con quien sí lo escribe.
    """
    page = re.sub(r"[.]", " ", text)
    page = re.sub(r"\b[345]g\b", " ", page)
    used = [False] * (len(page) + 1)
    found: list[str] = []

    def take(match: re.Match[str], token: str) -> None:
        if any(used[index] for index in range(match.start(), match.end())):
            return
        for index in range(match.start(), match.end()):
            used[index] = True
        if token not in found:
            found.append(token)

    for match in _PACK_MULTI_RE.finditer(page):
        take(match, f"{int(match.group(1))}x{_norm_qty(match.group(2), match.group(3))}")
    for match in _PACK_COUNT_RE.finditer(page):
        take(match, f"{int(match.group(1))}un")
    for match in _PACK_PACK_RE.finditer(page):
        take(match, f"{int(match.group(1))}un")
    for match in _PACK_N_PACK_RE.finditer(page):
        take(match, f"{int(match.group(1))}un")
    for match in _PACK_X_RE.finditer(page):
        take(match, f"{int(match.group(1))}un")
    for match in _PACK_SIZE_RE.finditer(page):
        take(match, _norm_qty(match.group(1), match.group(2)))
    if not any(_PACK_UNIT_TOKEN_RE.match(token) for token in found):
        found.append("1un")
    return tuple(sorted(found))


def _identity_text(product: Product) -> str:
    """Nombre + marca + specs: a veces la cantidad solo viene en atributos."""
    parts = [product.brand or "", product.name or ""]
    for key, value in (product.specifications or {}).items():
        parts.append(str(key))
        parts.append(str(value))
    return " ".join(parts)


VEHICLE_STORES = frozenset({"chileautos", "autocosmos"})


def _vehicle_info(product: Product) -> dict[str, str] | None:
    specs = product.specifications or {}
    vehicle_type = _fold(str(specs.get("vehicle_type") or ""))
    if str(product.store or "").lower() not in VEHICLE_STORES and vehicle_type not in {"car", "auto", "vehicle"}:
        return None
    year = re.sub(r"\D", "", str(specs.get("year") or ""))[:4]
    model = _fold(str(specs.get("model") or product.name or ""))
    version = _fold(str(specs.get("version") or ""))
    mileage = re.sub(r"\D", "", str(specs.get("mileage_km") or ""))
    return {
        "year": year,
        "model": model,
        "version": version,
        "mileage": mileage,
        "condition": condition_group(product.condition),
    }


def _vehicle_compare_code(product: Product, info: dict[str, str]) -> str:
    # Cada usado es una unidad física distinta. Nunca debe generar una oferta
    # "real" contra otro aviso del mismo modelo con kilometraje/estado propios.
    if info["condition"] == "used":
        return f"vehicle-used:{product.store}:{product.product_id}"
    if not info["version"]:
        return f"vehicle-new-unverified:{product.store}:{product.product_id}"
    brand = _fold(product.brand or "")
    identity = "|".join(part for part in (brand, info["model"], info["year"], info["version"]) if part)
    return f"vehicle-new:{identity or product.store + ':' + product.product_id}"


@dataclass(frozen=True, slots=True)
class Identity:
    """Las partes del nombre que identifican al producto, ya separadas."""

    brand: str
    models: tuple[str, ...]
    manufacturer_codes: tuple[str, ...]
    storage: tuple[str, ...]
    ram: tuple[str, ...]
    inches: str | None
    pack: tuple[str, ...]
    condition: str
    bundle: bool
    leftovers: tuple[str, ...]


def identity_of(product: Product) -> Identity:
    brand = _fold(product.brand or "")
    text = _alias_models(_fold(_identity_text(product)))
    manufacturer_codes = extract_manufacturer_codes(product)
    models = sorted({
        *[
            token for token in _MODEL_RE.findall(text)
            if len(token) >= 3 and token not in _GENERIC_MODEL_TOKENS
        ],
        *manufacturer_codes,
    })
    raw_storage: list[str] = []
    for amount, unit in _STORAGE_RE.findall(text):
        unit = "gb" if unit == "g" else unit
        token = f"{amount}{unit}"
        if token not in raw_storage:
            raw_storage.append(token)
    storage = _main_storage(raw_storage)
    ram = tuple(sorted({f"{match.group(1)}gb" for pattern in _RAM_PATTERNS for match in pattern.finditer(text)}))
    pack = pack_tokens(text)
    leftovers = [
        word
        for word in re.findall(r"[a-z0-9]{3,}", text)
        if word not in _STOP
        and word not in models
        and word not in storage
        and word not in pack
        and word not in _PACK_WORDS
        and word != brand
        and not word.isdigit()
    ]
    return Identity(
        brand=brand,
        models=tuple(models),
        manufacturer_codes=manufacturer_codes,
        storage=tuple(storage),
        ram=ram,
        inches=screen_size(text),
        pack=pack,
        condition=condition_group(product.condition),
        bundle=bool(_BUNDLE_RE.search(text)),
        leftovers=tuple(leftovers),
    )


def identity_fingerprint(product: Product, *, include_ram: bool = True) -> str:
    ident = identity_of(product)
    core = [ident.brand] if ident.brand else []
    core.extend(ident.models)
    core.extend(ident.storage)
    if include_ram:
        core.extend(f"ram:{value}" for value in ident.ram)
    if ident.inches:
        core.append(f"{ident.inches}in")
    core.extend(ident.pack)
    if ident.condition != "new_or_unknown":
        core.append(f"condition:{ident.condition}")
    if ident.bundle:
        core.append("bundle")
    if not ident.models and not ident.storage:
        core.extend(ident.leftovers[:5])
    elif ident.leftovers and not ident.models:
        core.extend(ident.leftovers[:3])
    return "|".join(part for part in core if part)


def pack_of(product: Product | dict[str, Any]) -> tuple[str, ...]:
    """Envase normalizado: 16 comprimidos ≠ 20; sin cantidad → 1un."""
    if not isinstance(product, Product):
        product = Product.from_dict(product)
    return identity_of(product).pack


def same_product_pack(left: Product | dict[str, Any], right: Product | dict[str, Any]) -> bool:
    return pack_of(left) == pack_of(right)


def same_product_identity(
    left: Product | dict[str, Any],
    right: Product | dict[str, Any],
    *,
    minimum: float = 0.84,
) -> bool:
    """Valida nuevamente dos avisos antes de comparar sus precios.

    Los documentos antiguos pueden conservar un ``compare_code`` creado con
    reglas anteriores. Esta comprobación evita mostrar una brecha falsa desde
    el primer despliegue, aun antes de volver a recorrer todo el catálogo.
    """
    one = left if isinstance(left, Product) else Product.from_dict(left)
    two = right if isinstance(right, Product) else Product.from_dict(right)
    confidence, _reason = identity_match_confidence(one, two)
    return confidence >= minimum


def same_model_family(left: Identity, right: Identity) -> bool:
    """Si una tienda publica el código largo del fabricante y la otra el corto.

    Ripley lista la misma tele como UN50U8000HGXZS y Falabella como U8000H. Se
    aceptan solo si coinciden marca, pulgadas y almacenamiento: así el
    'contiene' no junta un U8000H con un U8000HX de otra gama.
    """
    if not left.brand or left.brand != right.brand:
        return False
    if (
        left.inches != right.inches
        or left.storage != right.storage
        or (left.ram and right.ram and left.ram != right.ram)
        or left.pack != right.pack
        or left.condition != right.condition
        or left.bundle != right.bundle
    ):
        return False
    return any(
        (one in other or other in one) and min(len(one), len(other)) >= 5
        for one in left.models
        for other in right.models
    )


def identity_match_confidence(left: Product, right: Product) -> tuple[float, str]:
    """Confianza híbrida: IDs y atributos mandan; el texto solo desempata."""
    left_override = str(left.entity_override or "").strip()
    right_override = str(right.entity_override or "").strip()
    if left_override or right_override:
        return (1.0, "manual") if left_override and left_override == right_override else (0.0, "manual_split")

    left_vehicle = _vehicle_info(left)
    right_vehicle = _vehicle_info(right)
    if left_vehicle or right_vehicle:
        if not left_vehicle or not right_vehicle:
            return 0.0, "vehicle_type_mismatch"
        if left_vehicle["condition"] == "used" or right_vehicle["condition"] == "used":
            same_listing = (
                left.store == right.store
                and bool(left.product_id)
                and left.product_id == right.product_id
            )
            return (1.0, "same_vehicle_listing") if same_listing else (0.0, "used_vehicle_unique")
        if left_vehicle["year"] and right_vehicle["year"] and left_vehicle["year"] != right_vehicle["year"]:
            return 0.0, "vehicle_year_mismatch"
        if left_vehicle["model"] and right_vehicle["model"] and left_vehicle["model"] != right_vehicle["model"]:
            return 0.0, "vehicle_model_mismatch"
        if not left_vehicle["version"] or not right_vehicle["version"]:
            same_listing = left.store == right.store and left.product_id == right.product_id
            return (1.0, "same_vehicle_listing") if same_listing else (0.0, "vehicle_version_missing")
        if left_vehicle["version"] and right_vehicle["version"] and left_vehicle["version"] != right_vehicle["version"]:
            return 0.0, "vehicle_version_mismatch"

    one, two = identity_of(left), identity_of(right)
    if one.condition != two.condition or one.pack != two.pack or one.bundle != two.bundle:
        return 0.0, "strict_mismatch"
    if one.brand and two.brand and one.brand != two.brand:
        return 0.0, "brand_mismatch"
    for first, second, reason in (
        (one.storage, two.storage, "storage_mismatch"),
        (one.ram, two.ram, "ram_mismatch"),
        ((one.inches,) if one.inches else (), (two.inches,) if two.inches else (), "size_mismatch"),
    ):
        if first and second and first != second:
            return 0.0, reason

    ean_left, ean_right = extract_ean(left), extract_ean(right)
    if ean_left and ean_right:
        return (1.0, "gtin") if ean_left == ean_right else (0.0, "gtin_mismatch")
    if one.manufacturer_codes and two.manufacturer_codes:
        if set(one.manufacturer_codes).intersection(two.manufacturer_codes):
            return 0.99, "manufacturer_code"
        return 0.0, "manufacturer_code_mismatch"

    first_fp = identity_fingerprint(left)
    second_fp = identity_fingerprint(right)
    if first_fp and first_fp == second_fp:
        return 0.95, "identity"
    if same_model_family(one, two):
        return 0.93, "model_family"
    if one.models and two.models:
        compatible_model = any(
            first == second or ((first in second or second in first) and min(len(first), len(second)) >= 5)
            for first in one.models for second in two.models
        )
        if not compatible_model:
            return 0.0, "model_mismatch"
    if not one.brand or not two.brand:
        return 0.0, "insufficient_identity"

    left_tokens = set(one.leftovers).union(one.models)
    right_tokens = set(two.leftovers).union(two.models)
    shared = left_tokens.intersection(right_tokens)
    if len(shared) < 2:
        return 0.0, "insufficient_similarity"
    union = left_tokens.union(right_tokens)
    jaccard = len(shared) / len(union) if union else 0.0
    ordered_left = " ".join(sorted(left_tokens))
    ordered_right = " ".join(sorted(right_tokens))
    sequence = SequenceMatcher(None, ordered_left, ordered_right).ratio()
    similarity = 0.6 * jaccard + 0.4 * sequence
    if similarity < 0.72:
        return 0.0, "low_similarity"
    return round(0.78 + min(0.13, (similarity - 0.72) * 0.47), 3), "hybrid_text"


def _ean_compare_code(product: Product, ean: str) -> str:
    """Evita que un bundle o una condición usada compartan grupo por un EAN defectuoso."""
    ident = identity_of(product)
    qualifiers: list[str] = []
    if ident.bundle:
        qualifiers.append("bundle")
    if ident.condition != "new_or_unknown":
        qualifiers.append(ident.condition)
    if ident.pack != ("1un",):
        qualifiers.extend(ident.pack)
    suffix = ":".join(qualifiers)
    return f"ean:{ean}" + (f":{suffix}" if suffix else "")


def compare_code(product: Product) -> str:
    """Clave para agrupar la misma oferta entre tiendas."""
    if product.entity_override:
        return str(product.entity_override)
    vehicle = _vehicle_info(product)
    if vehicle:
        return _vehicle_compare_code(product, vehicle)
    ean = extract_ean(product)
    if ean:
        return _ean_compare_code(product, ean)
    fingerprint = identity_fingerprint(product)
    if fingerprint:
        return f"id:{fingerprint}"
    name = _fold(product.name or "")
    words = [word for word in re.findall(r"[a-z0-9]{3,}", name) if word not in _STOP]
    return f"name:{'|'.join(words[:8]) or product.product_id}"


def variant_key(row: dict[str, Any]) -> tuple[str, str]:
    """Misma tienda y mismo nombre: son variantes del mismo aviso."""
    return (row.get("store") or "", _fold(row.get("name") or ""))


# Cadenas que publican el mismo catálogo: el product_id de Falabella es el de
# Sodimac y Tottus, el de Paris es el de Easy. No son dos ofertas.
STORE_FAMILY = {
    "falabella": "falabella",
    "sodimac": "falabella",
    "tottus": "falabella",
    "paris": "cencosud",
    "easy": "cencosud",
}
FAMILY_ORDER = {"falabella": 0, "tottus": 1, "sodimac": 2, "paris": 0, "easy": 1}


def collapse_variants(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Una fila por aviso, la variante más barata, con el rango de las demás.

    Una cortina que viene en cuatro anchos son cuatro product_id con el mismo
    nombre y la tabla mostraba cuatro veces la misma línea. Solo se juntan
    nombres idénticos: dos colores con nombre distinto siguen separados, porque
    ahí el usuario sí está eligiendo.
    """
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[variant_key(row)].append(row)

    collapsed: list[dict[str, Any]] = []
    for group in buckets.values():
        group.sort(key=lambda row: (row.get("price") is None, row.get("price") or 10**12))
        best = dict(group[0])
        if len(group) > 1:
            prices = [row["price"] for row in group if row.get("price") is not None]
            best["variants"] = {
                "count": len(group),
                "min_price": min(prices) if prices else None,
                "max_price": max(prices) if prices else None,
            }
        collapsed.append(best)
    return collapsed


def is_catalog_mirror(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Si las dos filas son el mismo aviso publicado en cadenas hermanas."""
    key = _mirror_key(left)
    return key is not None and key == _mirror_key(right)


def _mirror_key(row: dict[str, Any]) -> tuple[str, str, Any] | None:
    family = STORE_FAMILY.get(row.get("store") or "")
    product_id = row.get("product_id") or ""
    if not family or not product_id:
        return None
    return (family, product_id, row.get("price"))


def collapse_mirrors(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Una fila cuando Falabella y Sodimac (o Paris y Easy) son el mismo aviso.

    Comparten catálogo y product_id. Si el precio es el mismo no hay comparación:
    es el aviso publicado dos veces. Si alguna cadena sale más barata, se dejan
    las dos, porque ahí sí hay que elegir.
    """
    buckets: dict[tuple[str, str, Any], list[dict[str, Any]]] = defaultdict(list)
    leftovers: list[dict[str, Any]] = []
    for row in rows:
        key = _mirror_key(row)
        if key is None:
            leftovers.append(row)
        else:
            buckets[key].append(row)

    collapsed: list[dict[str, Any]] = []
    for group in buckets.values():
        group.sort(
            key=lambda row: (
                FAMILY_ORDER.get(row.get("store") or "", 9),
                not row.get("from_scrape"),
                row.get("store") or "",
            )
        )
        best = dict(group[0])
        others = [row for row in group[1:]]
        if others:
            best["mirrors"] = {
                "stores": [row.get("store") for row in others],
                "store_titles": [row.get("store_title") or row.get("store") for row in others],
            }
        collapsed.append(best)
    return leftovers + collapsed


def collapse_display(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Colapsa variantes y espejos de la misma cadena, y recalcula comparables."""
    for group in groups:
        offers = collapse_mirrors(collapse_variants(group.get("offers") or []))
        priced_stores = {row.get("store") for row in offers if row.get("price") not in (None, 0)}
        comparable = len(priced_stores) > 1
        for row in offers:
            row["comparable"] = comparable
        group["offers"] = offers
        group["store_count"] = len({row.get("store") for row in offers})
        group["comparable"] = comparable
    return groups


def _cluster(products: list[Product]) -> list[list[int]]:
    """Junta por cualquier coincidencia: código de barras, huella o familia.

    Antes se agrupaba por una sola clave, y como cada tienda cae en un espacio
    distinto (unas publican el código de barras y otras no) el mismo producto
    quedaba en dos grupos que nunca se tocaban.
    """
    parent = list(range(len(products)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    idents = [identity_of(product) for product in products]
    by_override: dict[str, list[int]] = defaultdict(list)
    for index, product in enumerate(products):
        override = str(product.entity_override or "").strip()
        if override:
            by_override[override].append(index)
    for indexes in by_override.values():
        for index in indexes[1:]:
            union(indexes[0], index)

    by_ean: dict[str, int] = {}
    by_fp: dict[str, list[int]] = defaultdict(list)
    for index, product in enumerate(products):
        if product.entity_override:
            continue
        ean = extract_ean(product)
        fingerprint = identity_fingerprint(product) or None
        if ean:
            first = by_ean.get(ean)
            if first is None:
                by_ean[ean] = index
            elif (
                idents[first].pack == idents[index].pack
                and idents[first].bundle == idents[index].bundle
                and (
                    not idents[first].storage
                    or not idents[index].storage
                    or idents[first].storage == idents[index].storage
                )
                and (
                    not idents[first].inches
                    or not idents[index].inches
                    or idents[first].inches == idents[index].inches
                )
                and (
                not idents[first].ram or not idents[index].ram or idents[first].ram == idents[index].ram
                )
                and conditions_compatible(products[first].condition, product.condition)
            ):
                union(first, index)
        if fingerprint:
            base_fingerprint = identity_fingerprint(product, include_ram=False)
            by_fp[base_fingerprint].append(index)

    # RAM ausente puede unirse a una variante conocida solo cuando en el grupo
    # no compiten dos capacidades distintas. Esto evita que un registro
    # incompleto haga de puente entre 8 GB y 12 GB.
    for indexes in by_fp.values():
        known_ram = {idents[index].ram for index in indexes if idents[index].ram}
        if len(known_ram) > 1:
            for ram in known_ram:
                matches = [index for index in indexes if idents[index].ram == ram]
                for index in matches[1:]:
                    union(matches[0], index)
            continue
        for index in indexes[1:]:
            union(indexes[0], index)

    # El 'contiene' solo se busca entre candidatos con la misma marca y medida,
    # que son grupitos de pocos elementos.
    by_shape: dict[tuple[str, str | None, tuple[str, ...], tuple[str, ...], tuple[str, ...], str, bool], list[int]] = defaultdict(list)
    for index, ident in enumerate(idents):
        if ident.brand and ident.models and not products[index].entity_override:
            by_shape[(ident.brand, ident.inches, ident.storage, ident.ram, ident.pack, ident.condition, ident.bundle)].append(index)
    for bucket in by_shape.values():
        for position, left in enumerate(bucket):
            for right in bucket[position + 1 :]:
                if find(left) != find(right) and same_model_family(idents[left], idents[right]):
                    union(left, right)

    # Respaldo semántico acotado: solo cruza tiendas de la misma marca y nunca
    # puede saltarse una incompatibilidad de variante. Los grupos muy grandes
    # se omiten para mantener el costo predecible.
    semantic_buckets: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, ident in enumerate(idents):
        if ident.brand and not products[index].entity_override:
            semantic_buckets[(ident.brand, ident.condition)].append(index)
    for indexes in semantic_buckets.values():
        if len(indexes) > 120:
            continue
        for position, left in enumerate(indexes):
            for right in indexes[position + 1:]:
                if products[left].store == products[right].store or find(left) == find(right):
                    continue
                confidence, _method = identity_match_confidence(products[left], products[right])
                if confidence >= 0.84:
                    union(left, right)

    clusters: dict[int, list[int]] = defaultdict(list)
    for index in range(len(products)):
        clusters[find(index)].append(index)
    return list(clusters.values())


def _cluster_code(items: list[Product]) -> str:
    """Un código estable para el grupo: el de barras si alguna tienda lo trae."""
    override = next((str(product.entity_override) for product in items if product.entity_override), "")
    if override:
        return override
    for product in items:
        ean = extract_ean(product)
        if ean:
            return _ean_compare_code(product, ean)
    fingerprints = sorted({identity_fingerprint(product) for product in items} - {""})
    if fingerprints:
        return f"id:{fingerprints[0]}"
    return compare_code(items[0])


def _cluster_evidence(items: list[Product], code: str) -> tuple[float, str]:
    if len(items) <= 1:
        return 1.0, "single"
    if code.startswith("manual:"):
        return 1.0, "manual"
    best_per_item: list[tuple[float, str]] = []
    for index, item in enumerate(items):
        candidates = [identity_match_confidence(item, other) for pos, other in enumerate(items) if pos != index]
        best_per_item.append(max(candidates, key=lambda row: row[0], default=(0.0, "unknown")))
    confidence = min(row[0] for row in best_per_item)
    methods = [row[1] for row in best_per_item if row[0] == confidence]
    return round(confidence, 3), (methods[0] if methods else "unknown")


def compare_products(products: list[Product]) -> list[dict[str, Any]]:
    groups: dict[str, list[Product]] = {}
    for indices in _cluster(products):
        items = [products[index] for index in indices]
        groups[_cluster_code(items)] = items

    payload: list[dict[str, Any]] = []
    for code, items in groups.items():
        entity_confidence, match_method = _cluster_evidence(items, code)
        priced = [item for item in items if item.price not in (None, 0)]
        use_landed = shipping_comparable(priced)
        comparison_prices = {
            (item.store, item.product_id): (
                landed_price(item.price, item.shipping_cost) if use_landed else item.price
            )
            for item in priced
        }
        lowest_comparison = min((value for value in comparison_prices.values() if value is not None), default=None)
        cheapest_items = [
            item for item in priced
            if comparison_prices.get((item.store, item.product_id)) == lowest_comparison
        ]
        lowest_price = min((item.price or 0) for item in cheapest_items) if cheapest_items else None
        cheapest_stores = sorted(
            {item.store for item in cheapest_items}
        )
        offers = []
        for item in items:
            comparison_price = comparison_prices.get((item.store, item.product_id))
            is_lowest = comparison_price is not None and comparison_price == lowest_comparison
            row = item.to_dict(flatten_specs=False)
            row["compare_code"] = code
            row["entity_id"] = code
            row["entity_confidence"] = entity_confidence
            row["entity_match_method"] = match_method
            row["is_lowest"] = is_lowest
            row["total_price"] = landed_price(item.price, item.shipping_cost)
            row["comparison_price"] = comparison_price
            offers.append(row)
        offers.sort(key=lambda row: (
            row.get("comparison_price") is None,
            row.get("comparison_price") or 10**12,
            row.get("store") or "",
        ))
        kind = "manual" if code.startswith("manual:") else "ean" if code.startswith("ean:") else "identity" if code.startswith("id:") else "name"
        payload.append(
            {
                "compare_code": code,
                "kind": kind,
                "name": items[0].name,
                "brand": next((item.brand for item in items if item.brand), None),
                "lowest_price": lowest_price,
                "lowest_total_price": lowest_comparison if use_landed else None,
                "comparison_basis": "landed_price" if use_landed else "product_price",
                "entity_confidence": entity_confidence,
                "entity_match_method": match_method,
                "lowest_stores": cheapest_stores,
                "store_count": len({item.store for item in items}),
                "offer_count": len(items),
                "comparable": len({item.store for item in priced}) > 1,
                "offers": offers,
            }
        )
    payload.sort(
        key=lambda group: (
            not group["comparable"],
            group["lowest_price"] is None,
            group["lowest_price"] or 10**12,
            group["name"],
        )
    )
    return payload
