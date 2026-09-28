from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_bikehouse_target = parse_shopify_target

BikehouseStore = make_shopify_store(
    store_id="bikehouse",
    title="Bike House",
    site="bikehouse.cl",
    base="https://bikehouse.cl",
    category_help="Handle de colección Shopify",
)
