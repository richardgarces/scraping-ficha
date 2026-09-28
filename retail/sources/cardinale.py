from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_cardinale_target = parse_shopify_target

CardinaleStore = make_shopify_store(
    store_id="cardinale",
    title="Cardinale",
    site="www.cardinale.cl",
    base="https://www.cardinale.cl",
    category_help="Handle de colección Shopify",
)
