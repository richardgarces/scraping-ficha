from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_bix_target = parse_shopify_target

BixStore = make_shopify_store(
    store_id="bix",
    title="BIX",
    site="www.bix.cl",
    base="https://www.bix.cl",
    category_help="Handle de colección Shopify, por ejemplo hogar",
)
