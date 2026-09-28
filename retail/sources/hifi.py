from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_hifi_target = parse_shopify_target

HifiStore = make_shopify_store(
    store_id="hifi",
    title="HiFi",
    site="www.hifi.cl",
    base="https://www.hifi.cl",
    category_help="Handle de colección Shopify, por ejemplo audio",
)
