from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_lush_target = parse_shopify_target

LushStore = make_shopify_store(
    store_id="lush",
    title="Lush",
    site="www.lush.cl",
    base="https://www.lush.cl",
    category_help="Handle de colección Shopify",
)
