from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from retail.intent import conflict, parse
from retail.models import Product
from retail import priceband

_STOP = {
    "el",
    "la",
    "los",
    "las",
    "un",
    "una",
    "unos",
    "unas",
    "de",
    "del",
    "y",
    "o",
    "con",
    "para",
    "por",
    "en",
    "al",
    "the",
    "of",
    "and",
    "gb",
    "g",
    # Preferencia de precio: no tienen que aparecer en el nombre del producto.
    "barato",
    "barata",
    "baratos",
    "baratas",
    "economico",
    "economica",
    "economicos",
    "economicas",
    "gamer",
    "gaming",
    "premium",
    "profesional",
    "profesionales",
}

_ALIASES: dict[str, set[str]] = {
    "celular": {"celular", "celulares", "telefono", "telefonos", "smartphone", "smartphones", "galaxy", "iphone", "movil", "moviles", "phone"},
    "notebook": {"notebook", "notebooks", "laptop", "laptops", "portatil", "portatiles", "macbook"},
    "leche": {"leche", "leches"},
    "silla": {"silla", "sillas"},
    "carpa": {"carpa", "carpas"},
    "colchon": {"colchon", "colchones"},
    "zapatilla": {"zapatilla", "zapatillas", "sneaker", "sneakers"},
    "polera": {"polera", "poleras", "poleron", "polerones"},
}

_SPEC_RE = re.compile(r"^\d{2,5}(gb|g|tb|mb|mah|w|hz|cm|mm|pulgadas|litros|in)$")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_MEASURE_RE = re.compile(r"(\d{1,4})\s*(?:pulgadas?|pulg\.?|\"|'')")
_LITERS_RE = re.compile(r"(\d{1,4})\s*(?:litros?|lts?\.?)\b")


def fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("+", " ").replace("-", " ").replace("/", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


# Mismo orden/heurística que categoryIconKind en app.js (Explora rápido).
_CATEGORY_ICON_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"calzado|zapato"), "calzado"),
    (re.compile(r"deporte|aire libre"), "sports"),
    (re.compile(r"accesorios moda|moda"), "fashion"),
    (re.compile(r"electrodomest"), "appliance"),
    (re.compile(r"tecnolog"), "tech"),
    (re.compile(r"audio|musica"), "audio"),
    (re.compile(r"belleza|higiene|salud|farmacia"), "beauty"),
    (re.compile(r"alimento|bebida|gastronom"), "food"),
    (re.compile(r"supermercado"), "market"),
    (re.compile(r"ferreter|herramient|maquina|construccion"), "tools"),
    (re.compile(r"cocina|bano"), "kitchen"),
    (re.compile(r"juguete"), "toys"),
    (re.compile(r"automotriz|autos?\b"), "auto"),
    (re.compile(r"jardin|terraza"), "garden"),
    (re.compile(r"decohogar|hogar"), "home"),
    (re.compile(r"bebes?|infantil"), "baby"),
    (re.compile(r"libreria|libros?"), "books"),
    (re.compile(r"mascota"), "pets"),
)


def category_icon_kind(value: str) -> str:
    """Slug CSS de icono para una etiqueta de categoría (fallback: other)."""
    key = fold(value)
    for pattern, kind in _CATEGORY_ICON_RULES:
        if pattern.search(key):
            return kind
    return "other"


def _normalize_spec(token: str) -> str:
    if token.endswith("g") and token[:-1].isdigit() and not token.endswith("gb"):
        return f"{token[:-1]}gb"
    return token


def _collapse_measures(text: str) -> str:
    """"50 pulgadas" es una sola medida, no dos palabras que haya que exigir aparte."""
    text = _MEASURE_RE.sub(r"\1pulgadas", text)
    return _LITERS_RE.sub(r"\1litros", text)


def tokenize(query: str) -> list[str]:
    folded = _collapse_measures(fold(query))
    tokens = []
    for raw in _TOKEN_RE.findall(folded):
        token = _normalize_spec(raw)
        if token in _STOP or len(token) < 2:
            continue
        tokens.append(token)
    return tokens


def _kind(token: str) -> str:
    if _SPEC_RE.match(token):
        return "spec"
    if any(ch.isalpha() for ch in token) and any(ch.isdigit() for ch in token):
        return "model"
    if token in _ALIASES or any(token in aliases for aliases in _ALIASES.values()):
        return "category"
    return "keyword"


def _expansions(token: str) -> set[str]:
    found = {token, _normalize_spec(token)}
    if token in _ALIASES:
        found.update(_ALIASES[token])
    for canonical, aliases in _ALIASES.items():
        if token in aliases:
            found.add(canonical)
            found.update(aliases)
    return found


def _haystack(product: Product) -> str:
    parts = [product.name, product.brand or "", product.sku_id or "", product.product_id or "", product.category or ""]
    return fold(" ".join(parts))


@dataclass(slots=True)
class Relevance:
    score: float
    accepted: bool
    matched: list[str]
    missing: list[str]
    reason: str | None = None


def score_product(query: str, product: Product) -> Relevance:
    tokens = tokenize(query)
    if not tokens:
        return Relevance(score=0.0, accepted=False, matched=[], missing=[])
    text = _haystack(product)
    compact = text.replace(" ", "")
    matched: list[str] = []
    missing: list[str] = []
    weight = 0.0
    total = 0.0
    models = [token for token in tokens if _kind(token) == "model"]
    categories = [token for token in tokens if _kind(token) == "category"]
    keywords = [token for token in tokens if _kind(token) == "keyword"]
    specs = [token for token in tokens if _kind(token) == "spec"]

    words = set(text.split())

    def hits(token: str) -> bool:
        for alias in _expansions(token):
            if alias in words:
                return True
            # el pegado sirve para specs como "512gb" escrito "512 gb", pero con
            # palabras cortas "tv" calzaría dentro de "tveto" y trae cualquier cosa.
            if len(alias) >= 4 and alias in compact:
                return True
        return False

    for token in tokens:
        kind = _kind(token)
        total += 3 if kind == "model" else 2 if kind in {"category", "keyword"} else 1
        if hits(token):
            matched.append(token)
            weight += 3 if kind == "model" else 2 if kind in {"category", "keyword"} else 1
        else:
            missing.append(token)

    model_ok = all(hits(token) for token in models)
    category_ok = True
    if categories:
        category_ok = any(hits(token) for token in categories)
    keyword_ok = True
    if keywords and not models:
        needed = len(keywords) if len(keywords) <= 2 else max(1, (len(keywords) + 1) // 2)
        keyword_ok = sum(1 for token in keywords if hits(token)) >= needed
    accepted = model_ok and category_ok and keyword_ok
    if not tokens:
        accepted = False
    score = weight / total if total else 0.0
    if specs and any(hits(token) for token in specs):
        score = min(1.0, score + 0.08)
    reason = (
        conflict(
            parse(fold(query)),
            fold(" ".join(part for part in (product.name, product.brand or "", product.category or "") if part)),
            query=fold(query),
        )
        if accepted
        else None
    )
    if reason:
        accepted = False
    return Relevance(
        score=round(score, 3),
        accepted=accepted,
        matched=matched,
        missing=missing,
        reason=reason,
    )


def filter_relevant(
    query: str,
    products: list[Product],
    extra_scores: dict[tuple[str, str], float] | None = None,
    *,
    price_band: bool = True,
) -> tuple[list[Product], list[Product], dict[tuple[str, str], Relevance]]:
    extras = extra_scores or {}
    kept: list[Product] = []
    discarded: list[Product] = []
    details: dict[tuple[str, str], Relevance] = {}
    for product in products:
        key = (product.store, product.product_id or product.name)
        item = score_product(query, product)
        semantic = extras.get(key, 0.0)
        if semantic:
            item = Relevance(
                score=round(min(1.0, max(item.score, (item.score * 0.7) + (semantic * 0.3))), 3),
                accepted=item.accepted,
                matched=item.matched,
                missing=item.missing,
                reason=item.reason,
            )
        details[key] = item
        if item.accepted:
            kept.append(product)
        else:
            discarded.append(product)
    if price_band:
        kept, discarded = _apply_price_band(query, kept, discarded, details)
    kept.sort(key=lambda product: (-details[(product.store, product.product_id or product.name)].score, product.price or 10**12))
    return kept, discarded, details


def _apply_price_band(
    query: str,
    kept: list[Product],
    discarded: list[Product],
    details: dict[tuple[str, str], Relevance],
) -> tuple[list[Product], list[Product]]:
    band = priceband.fit([item.price or 0 for item in kept], priceband.preference(query))
    if band is None:
        return kept, discarded
    still: list[Product] = []
    for product in kept:
        key = (product.store, product.product_id or product.name)
        reason = priceband.conflict(product.price, band)
        if not reason:
            still.append(product)
            continue
        item = details[key]
        details[key] = Relevance(
            score=item.score,
            accepted=False,
            matched=item.matched,
            missing=item.missing,
            reason=reason,
        )
        discarded.append(product)
    return still, discarded
