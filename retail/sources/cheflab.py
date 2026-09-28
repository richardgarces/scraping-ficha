from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_cheflab_target = parse_shopify_target

CheflabStore = make_shopify_store(
    store_id="cheflab",
    title="Chef Lab",
    site="cheflab.cl",
    base="https://cheflab.cl",
    category_help="Handle de colección Shopify, por ejemplo cocina",
)
