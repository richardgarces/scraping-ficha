from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_belkin_target = parse_shopify_target

BelkinStore = make_shopify_store(
    store_id="belkin",
    title="Belkin",
    site="www.belkin.cl",
    base="https://www.belkin.cl",
    category_help="Handle de colección Shopify",
)
