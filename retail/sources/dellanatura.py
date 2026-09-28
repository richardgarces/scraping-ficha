from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_dellanatura_target = parse_shopify_target

DellanaturaStore = make_shopify_store(
    store_id="dellanatura",
    title="Dellanatura",
    site="www.dellanatura.cl",
    base="https://www.dellanatura.cl",
    category_help="Handle de colección Shopify",
)
