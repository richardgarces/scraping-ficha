from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_limonada_target = parse_shopify_target

LimonadaStore = make_shopify_store(
    store_id="limonada",
    title="Limonada",
    site="www.limonada.cl",
    base="https://www.limonada.cl",
    category_help="Handle de colección Shopify",
)
