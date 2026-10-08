from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_superstore_target = parse_shopify_target

SuperstoreStore = make_shopify_store(
    store_id="superstore",
    title="SuperStore",
    site="www.superstore.cl",
    base="https://www.superstore.cl",
    category_help="Handle de colección Shopify",
)
