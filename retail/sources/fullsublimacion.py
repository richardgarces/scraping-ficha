from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_fullsublimacion_target = parse_shopify_target

FullsublimacionStore = make_shopify_store(
    store_id="fullsublimacion",
    title="Full Sublimación",
    site="www.fullsublimacion.cl",
    base="https://www.fullsublimacion.cl",
    category_help="Handle de colección Shopify, por ejemplo sublimacion",
)
