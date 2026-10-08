from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_atletis_target = parse_shopify_target

AtletisStore = make_shopify_store(
    store_id="atletis",
    title="Atletis",
    site="www.atletis.cl",
    base="https://www.atletis.cl",
    category_help="Handle de colección Shopify",
)
