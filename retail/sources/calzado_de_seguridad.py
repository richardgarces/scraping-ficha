from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_calzado_de_seguridad_target = parse_shopify_target

CalzadoDeSeguridadStore = make_shopify_store(
    store_id="calzado_de_seguridad",
    title="Calzado de Seguridad",
    site="www.calzadodeseguridad.cl",
    base="https://www.calzadodeseguridad.cl",
    category_help="Handle de colección Shopify",
)
