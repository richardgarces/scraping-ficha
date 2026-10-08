from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_novahus_target = parse_shopify_target

NovahusStore = make_shopify_store(
    store_id="novahus",
    title="Novahus",
    site="www.novahus.cl",
    base="https://www.novahus.cl",
    category_help="Handle de colección Shopify",
)
