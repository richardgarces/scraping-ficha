from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_contrapunto_target = parse_shopify_target

ContrapuntoStore = make_shopify_store(
    store_id="contrapunto",
    title="Contrapunto",
    site="www.contrapunto.cl",
    base="https://www.contrapunto.cl",
    category_help="Handle de colección Shopify",
)
