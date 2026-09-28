from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_honutrition_target = parse_shopify_target

HonutritionStore = make_shopify_store(
    store_id="honutrition",
    title="HO Nutrition",
    site="www.honutrition.cl",
    base="https://www.honutrition.cl",
    category_help="Handle de colección Shopify, por ejemplo suplementos",
)
