from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_needle_target = parse_shopify_target

NeedleStore = make_shopify_store(
    store_id="needle",
    title="Needle",
    site="www.needle.cl",
    base="https://www.needle.cl",
    category_help="Handle de colección Shopify",
)
