from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_totaltools_target = parse_shopify_target

TotaltoolsStore = make_shopify_store(
    store_id="totaltools",
    title="Total Tools",
    site="www.totaltools.cl",
    base="https://www.totaltools.cl",
    category_help="Handle de colección Shopify",
)
