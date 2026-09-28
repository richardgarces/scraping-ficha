from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_blustore_target = parse_shopify_target

BlustoreStore = make_shopify_store(
    store_id="blustore",
    title="Blu Store",
    site="www.blustore.cl",
    base="https://www.blustore.cl",
    category_help="Handle de colección Shopify, por ejemplo domotica",
)
