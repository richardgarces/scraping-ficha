from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_nooki_target = parse_shopify_target

NookiStore = make_shopify_store(
    store_id="nooki",
    title="Nooki",
    site="www.nooki.cl",
    base="https://www.nooki.cl",
    category_help="Handle de colección Shopify, por ejemplo k-beauty",
)
