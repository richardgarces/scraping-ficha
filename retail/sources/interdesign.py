from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_interdesign_target = parse_shopify_target

InterdesignStore = make_shopify_store(
    store_id="interdesign",
    title="Interdesign",
    site="www.interdesign.cl",
    base="https://www.interdesign.cl",
    category_help="Handle de colección Shopify",
)
