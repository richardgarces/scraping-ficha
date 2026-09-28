from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_garmin_target = parse_shopify_target

GarminStore = make_shopify_store(
    store_id="garmin",
    title="Garmin",
    site="garminstore.cl",
    base="https://garminstore.cl",
    category_help="Handle de colección Shopify, por ejemplo smartwatch",
)
