from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_ecook_target = parse_shopify_target

EcookStore = make_shopify_store(
    store_id="ecook",
    title="eCook",
    site="ecook.cl",
    base="https://ecook.cl",
    category_help="Handle de colección Shopify, por ejemplo platos",
)
