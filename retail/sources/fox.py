from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_fox_target = parse_shopify_target

FoxStore = make_shopify_store(
    store_id="fox",
    title="Fox",
    site="trailstore.cl",
    base="https://trailstore.cl",
    category_help="Handle de colección Shopify, por ejemplo cascos",
)
