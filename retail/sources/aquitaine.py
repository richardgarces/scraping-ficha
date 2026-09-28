from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_aquitaine_target = parse_shopify_target

AquitaineStore = make_shopify_store(
    store_id="aquitaine",
    title="Parfumerie d'Aquitaine",
    site="www.parfumeriedaquitaine.cl",
    base="https://www.parfumeriedaquitaine.cl",
    category_help="Handle de colección Shopify, por ejemplo perfumes",
)
