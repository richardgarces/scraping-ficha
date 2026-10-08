from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_tehtools_target = parse_shopify_target

TehtoolsStore = make_shopify_store(
    store_id="tehtools",
    title="Tehtools",
    site="www.tehtools.cl",
    base="https://www.tehtools.cl",
    category_help="Handle de colección Shopify",
)
