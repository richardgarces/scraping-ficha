from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_kallfu_target = parse_shopify_target

KallfuStore = make_shopify_store(
    store_id="kallfu",
    title="Kallfü",
    site="www.kallfu.cl",
    base="https://www.kallfu.cl",
    category_help="Handle de colección Shopify, por ejemplo muebles",
)
