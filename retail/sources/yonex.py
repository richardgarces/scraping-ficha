from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_yonex_target = parse_shopify_target

YonexStore = make_shopify_store(
    store_id="yonex",
    title="Yonex",
    site="www.yonex.cl",
    base="https://www.yonex.cl",
    category_help="Handle de colección Shopify, por ejemplo tenis",
)
