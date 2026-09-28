from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_dominame_target = parse_shopify_target

DominameStore = make_shopify_store(
    store_id="dominame",
    title="Dominame",
    site="www.dominame.cl",
    base="https://www.dominame.cl",
    category_help="Handle de colección Shopify, por ejemplo lubricantes",
)
