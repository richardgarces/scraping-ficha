from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_cscalzado_target = parse_shopify_target

CscalzadoStore = make_shopify_store(
    store_id="cscalzado",
    title="CS Calzado de Seguridad",
    site="www.calzadodeseguridad.cl",
    base="https://www.calzadodeseguridad.cl",
    category_help="Handle de colección Shopify, por ejemplo calzado de seguridad",
)
