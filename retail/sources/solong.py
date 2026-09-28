from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_solong_target = parse_shopify_target

SolongStore = make_shopify_store(
    store_id="solong",
    title="So Long",
    site="www.solong.cl",
    base="https://www.solong.cl",
    category_help="Handle de colección Shopify, por ejemplo opticos",
)
