from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_alisha_target = parse_shopify_target

AlishaStore = make_shopify_store(
    store_id="alisha",
    title="Alisha Perfumes",
    site="www.alishaperfumes.cl",
    base="https://www.alishaperfumes.cl",
    category_help="Handle de colección Shopify, por ejemplo perfumes",
)
