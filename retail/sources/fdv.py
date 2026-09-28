from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_fdv_target = parse_shopify_target

FdvStore = make_shopify_store(
    store_id="fdv",
    title="FDV",
    site="www.fdv.cl",
    base="https://www.fdv.cl",
    category_help="Handle de colección Shopify",
)
