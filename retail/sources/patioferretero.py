from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_patioferretero_target = parse_shopify_target

PatioferreteroStore = make_shopify_store(
    store_id="patioferretero",
    title="Patio Ferretero",
    site="www.patioferretero.cl",
    base="https://www.patioferretero.cl",
    category_help="Handle de colección Shopify, por ejemplo ferreteria",
)
