from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_apro_target = parse_shopify_target

AproStore = make_shopify_store(
    store_id="apro",
    title="Apro",
    site="www.apro.cl",
    base="https://www.apro.cl",
    category_help="Handle de colección Shopify, por ejemplo guantes",
)
