from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_nutrapharm_target = parse_shopify_target

NutrapharmStore = make_shopify_store(
    store_id="nutrapharm",
    title="Nutrapharm",
    site="www.nutrapharm.cl",
    base="https://www.nutrapharm.cl",
    category_help="Handle de colección Shopify",
)
