from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_trail_store_target = parse_shopify_target

TrailStoreStore = make_shopify_store(
    store_id="trail_store",
    title="Trail Store",
    site="www.trailstore.cl",
    base="https://www.trailstore.cl",
    category_help="Handle de colección Shopify",
)
