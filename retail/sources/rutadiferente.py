from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_rutadiferente_target = parse_shopify_target

RutadiferenteStore = make_shopify_store(
    store_id="rutadiferente",
    title="Ruta Diferente",
    site="www.rutadiferente.cl",
    base="https://www.rutadiferente.cl",
    category_help="Handle de colección Shopify, por ejemplo camping",
)
