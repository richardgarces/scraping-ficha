from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_allnutrition_target = parse_shopify_target

AllnutritionStore = make_shopify_store(
    store_id="allnutrition",
    title="All Nutrition",
    site="www.allnutrition.cl",
    base="https://www.allnutrition.cl",
    category_help="Handle de colección Shopify",
)
