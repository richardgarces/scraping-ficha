from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_baepink_target = parse_shopify_target

BaepinkStore = make_shopify_store(
    store_id="baepink",
    title="Baepink",
    site="www.baepink.cl",
    base="https://www.baepink.cl",
    category_help="Handle de colección Shopify",
)
