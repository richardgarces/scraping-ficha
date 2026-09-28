from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_vadell_target = parse_shopify_target

VadellStore = make_shopify_store(
    store_id="vadell",
    title="Vadell",
    site="vadell.cl",
    base="https://vadell.cl",
    category_help="Handle de colección Shopify, por ejemplo taca-taca",
)
