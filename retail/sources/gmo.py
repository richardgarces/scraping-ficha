from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_gmo_target = parse_shopify_target

GmoStore = make_shopify_store(
    store_id="gmo",
    title="GMO",
    site="www.gmo.cl",
    base="https://www.gmo.cl",
    category_help="Handle de colección Shopify",
)
