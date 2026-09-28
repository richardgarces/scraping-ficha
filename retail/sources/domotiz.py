from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_domotiz_target = parse_shopify_target

DomotizStore = make_shopify_store(
    store_id="domotiz",
    title="Domótiz",
    site="www.domotiz.cl",
    base="https://www.domotiz.cl",
    category_help="Handle de colección Shopify, por ejemplo interruptores",
)
