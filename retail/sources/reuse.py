from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_reuse_target = parse_shopify_target

ReuseStore = make_shopify_store(
    store_id="reuse",
    title="Reuse",
    site="www.reuse.cl",
    base="https://www.reuse.cl",
    category_help="Handle de colección Shopify",
)
