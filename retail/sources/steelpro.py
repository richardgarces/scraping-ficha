from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_steelpro_target = parse_shopify_target

SteelproStore = make_shopify_store(
    store_id="steelpro",
    title="Steelpro",
    site="www.steelpro.cl",
    base="https://www.steelpro.cl",
    category_help="Handle de colección Shopify, por ejemplo cascos",
)
