from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_stretto_target = parse_shopify_target

StrettoStore = make_shopify_store(
    store_id="stretto",
    title="Stretto",
    site="www.stretto.cl",
    base="https://www.stretto.cl",
    category_help="Handle de colección Shopify",
)
