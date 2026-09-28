from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_migo_target = parse_shopify_target

MigoStore = make_shopify_store(
    store_id="migo",
    title="Migo",
    site="www.migo.cl",
    base="https://www.migo.cl",
    category_help="Handle de colección Shopify",
)
