"""Qué tipo de producto se pidió, para descartar accesorios que lo nombran.

Buscar "tv 50 pulgadas" traía racks y soportes: comparten todas las palabras de
la consulta. Acá se decide si el producto *es* lo pedido o solo lo menciona.

También señala consultas que parecen medicamentos (para sumar farmacias al
fallback cuando no hay genérico en el índice).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_INCH_RE = re.compile(r"(\d{2,3})\s*(?:pulgadas?|pulg\.?|\"|'')")
# Dosis con unidad: "500 mg", "10mg", "1000 ui". "mg" solo no alcanza.
_DOSE_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:mg|mcg|ug|ml|ui|iu)\b")
# Sufijos INN frecuentes (token completo; se exige largo ≥6 al aplicar).
_DRUG_SUFFIX_RE = re.compile(
    r"^.+(?:"
    r"cilina|ciclina|statina|sartan|prazol|azepam|zolam|"
    r"conazol|micina|floxacino|gliptina|glutida|olol|"
    r"dipina|formina|pril|adina"
    r")$"
)
_FOR = {"para", "compatible", "compatibles"}
_INCH_RANGE = (10, 120)

# Palabras/frases de farmacia (ya plegadas). Preferir términos ≥4 letras o frases.
PHARMACY_WORDS: frozenset[str] = frozenset(
    {
        "medicamento",
        "medicamentos",
        "farmaco",
        "farmacos",
        "remedio",
        "remedios",
        "pastilla",
        "pastillas",
        "farmacia",
        "farmacias",
        "farmaceutico",
        "farmaceutica",
        "analgesico",
        "analgesicos",
        "antipiretico",
        "antipireticos",
        "antiinflamatorio",
        "antiinflamatorios",
        "antibiotico",
        "antibioticos",
        "antigripal",
        "antigripales",
        "antihistaminico",
        "antihistaminicos",
        "mucolitico",
        "expectorante",
        "jarabe",
        "jarabes",
        "capsula",
        "capsulas",
        "comprimido",
        "comprimidos",
        "tableta",
        "tabletas",
        "gragea",
        "grageas",
        "inyeccion",
        "inyecciones",
        "inyectable",
        "inyectables",
        "unguento",
        "pomada",
        "pomadas",
        "ovulo",
        "ovulos",
        "supositorio",
        "supositorios",
        "ampolla",
        "ampollas",
        "blister",
        "receta",
    }
)
PHARMACY_PHRASES: tuple[str, ...] = (
    "solucion oral",
    "suspension oral",
    "gotas oftalmicas",
    "gotas nasales",
    "venta libre",
    "receta medica",
    "sin receta",
)

DEVICES: dict[str, tuple[str, ...]] = {
    "televisor": ("tv", "tvs", "televisor", "televisores", "television", "televisiones", "smarttv"),
    "celular": ("celular", "celulares", "smartphone", "smartphones", "telefono", "iphone", "galaxy"),
    "notebook": ("notebook", "notebooks", "laptop", "laptops", "macbook", "portatil"),
    "tablet": ("tablet", "tablets", "ipad"),
    "monitor": ("monitor", "monitores"),
    "refrigerador": ("refrigerador", "refrigeradores", "freezer", "congelador"),
    "lavadora": ("lavadora", "lavadoras", "secadora", "secadoras"),
    "microondas": ("microondas",),
    "aspiradora": ("aspiradora", "aspiradoras"),
    "audifonos": ("audifonos", "audifono", "auriculares", "airpods"),
    "parlante": ("parlante", "parlantes", "altavoz"),
    "consola": ("consola", "consolas", "playstation", "xbox", "nintendo"),
    "camara": ("camara", "camaras", "gopro"),
    "reloj": ("reloj", "relojes", "smartwatch", "smartband"),
    "impresora": ("impresora", "impresoras"),
    "bicicleta": ("bicicleta", "bicicletas"),
}

ACCESSORIES: dict[str, tuple[str, ...]] = {
    "rack": ("rack", "racks"),
    "mueble": ("mueble", "muebles", "repisa", "repisas", "estante", "estanteria", "velador", "comoda"),
    "soporte": ("soporte", "soportes", "pedestal", "tripode", "brazo"),
    "funda": ("funda", "fundas", "carcasa", "carcasas", "estuche", "cover"),
    "protector": ("protector", "protectores", "lamina", "laminas", "mica"),
    "cable": ("cable", "cables", "adaptador", "adaptadores", "hub"),
    "cargador": ("cargador", "cargadores", "powerbank", "bateria"),
    "control": ("control", "controles", "mando", "joystick"),
    "bolso": ("bolso", "bolsos", "maleta", "maletin", "mochila", "morral"),
    "repuesto": ("repuesto", "repuestos", "filtro", "filtros"),
}

# Un televisor no tiene puertas ni cajones; un refrigerador sí, por eso la señal
# solo se aplica a los aparatos que nunca son muebles.
FURNITURE_MARKERS = ("puertas", "cajones", "melamina", "aglomerado", "entrepano", "entrepanos")
NEVER_FURNITURE = {
    "televisor",
    "celular",
    "notebook",
    "tablet",
    "monitor",
    "audifonos",
    "parlante",
    "camara",
    "reloj",
    "consola",
}

# Consultas de moda con homónimos alimenticios (p. ej. corbata = necktie vs farfalle).
# Si la consulta pide la prenda y el título trae señales de comida, se descarta.
FASHION_FOOD_AMBIGUOUS: dict[str, frozenset[str]] = {
    "corbata": frozenset(
        {
            "fideo",
            "fideos",
            "pasta",
            "pastas",
            "spaghetti",
            "spaghettini",
            "mostaccioli",
            "farfalle",
            "fettuccine",
            "fusilli",
            "canelones",
            "lasagna",
            "lasana",
            "raviol",
            "ravioles",
            "lucchetti",
            "carozzi",
            "napolitana",
        }
    ),
    "corbatas": frozenset(
        {
            "fideo",
            "fideos",
            "pasta",
            "pastas",
            "spaghetti",
            "farfalle",
            "lucchetti",
            "carozzi",
        }
    ),
}


@dataclass(slots=True)
class Intent:
    devices: set[str]
    accessories: set[str]
    inches: int | None
    pharmacy: bool = False

    def __bool__(self) -> bool:
        return bool(self.devices or self.accessories or self.inches or self.pharmacy)


def _first_positions(tokens: list[str], table: dict[str, tuple[str, ...]]) -> dict[str, int]:
    """Primera posición en la que aparece cada tipo canónico."""
    found: dict[str, int] = {}
    for index, token in enumerate(tokens):
        for canonical, words in table.items():
            if token in words:
                found.setdefault(canonical, index)
    return found


def _inches(text: str) -> int | None:
    match = _INCH_RE.search(text)
    if not match:
        return None
    value = int(match.group(1))
    return value if _INCH_RANGE[0] <= value <= _INCH_RANGE[1] else None


def _has_pharmacy_phrase(text: str) -> bool:
    return any(phrase in text for phrase in PHARMACY_PHRASES)


def _has_drug_like_token(tokens: list[str]) -> bool:
    return any(_DRUG_SUFFIX_RE.match(token) for token in tokens if len(token) >= 6)


_DOSE_UNITS = frozenset({"mg", "mcg", "ug", "ml", "ui", "iu"})
_DOSE_TOKEN_RE = re.compile(r"^\d+(?:[.,]\d+)?(?:mg|mcg|ug|ml|ui|iu)$")


def _has_dose_with_name(text: str, tokens: list[str]) -> bool:
    """«amoxicilina 500mg» sí; «500 mg» / «500mg» / «mg» solos no."""
    if not _DOSE_RE.search(text):
        return False
    return any(
        len(token) >= 4
        and any(char.isalpha() for char in token)
        and token not in _DOSE_UNITS
        and not _DOSE_TOKEN_RE.match(token)
        and token not in {"pulgadas", "pulgada"}
        for token in tokens
    )


def looks_pharmacy(query: str) -> bool:
    """True si la consulta (ya plegada) parece medicamento / farmacia.

    No usa el token «mg» solo: hace falta palabra de farmacia, forma farmacéutica,
    frase, sufijo tipo INN o nombre + dosis (500 mg).
    """
    text = (query or "").strip()
    if not text:
        return False
    if _has_pharmacy_phrase(text):
        return True
    tokens = _TOKEN_RE.findall(text)
    if any(token in PHARMACY_WORDS for token in tokens):
        return True
    if _has_drug_like_token(tokens):
        return True
    return _has_dose_with_name(text, tokens)


def parse(query: str) -> Intent:
    """query ya viene plegada (sin tildes, minúsculas)."""
    tokens = _TOKEN_RE.findall(query)
    return Intent(
        devices=set(_first_positions(tokens, DEVICES)),
        accessories=set(_first_positions(tokens, ACCESSORIES)),
        inches=_inches(query),
        pharmacy=looks_pharmacy(query),
    )


def fashion_food_conflict(query: str, name: str) -> str | None:
    """Descarta comida cuando la consulta pide una prenda con homónimo alimenticio.

    «corbata» en moda es necktie; «fideos corbatas» / Lucchetti sí es pasta.
    """
    query_tokens = set(_TOKEN_RE.findall(query or ""))
    if not query_tokens:
        return None
    name_tokens = set(_TOKEN_RE.findall(name or ""))
    for term, food_markers in FASHION_FOOD_AMBIGUOUS.items():
        if term not in query_tokens:
            continue
        # La consulta ya habla de comida: es pasta, no moda.
        if query_tokens & food_markers:
            continue
        hit = name_tokens & food_markers
        if hit:
            return f"es comida ({sorted(hit)[0]}), no moda"
    return None


def conflict(intent: Intent, name: str, *, query: str = "") -> str | None:
    """Motivo por el que el producto no es lo pedido, o None si calza."""
    food_reason = fashion_food_conflict(query, name) if query else None
    if food_reason:
        return food_reason
    if not intent.devices:
        return None
    tokens = _TOKEN_RE.findall(name)
    wanted = {
        device: position
        for device, position in _first_positions(tokens, DEVICES).items()
        if device in intent.devices
    }
    pedido = sorted(intent.devices)[0]

    for accessory, position in _first_positions(tokens, ACCESSORIES).items():
        if accessory in intent.accessories:
            continue
        if not wanted or position < min(wanted.values()):
            return f"es un {accessory}, no un {pedido}"

    if (
        "mueble" not in intent.accessories
        and intent.devices <= NEVER_FURNITURE
        and any(marker in tokens for marker in FURNITURE_MARKERS)
    ):
        return f"es un mueble, no un {pedido}"

    if not intent.accessories:
        for device, position in wanted.items():
            preceding = tokens[max(0, position - 2) : position]
            if any(word in _FOR for word in preceding):
                return f"es un accesorio para {device}"

    if intent.inches:
        sizes = {
            int(token)
            for token in tokens
            if token.isdigit() and _INCH_RANGE[0] <= int(token) <= _INCH_RANGE[1]
        }
        if sizes and intent.inches not in sizes:
            return f"mide {sorted(sizes)[0]}\" y pediste {intent.inches}\""

    return None
