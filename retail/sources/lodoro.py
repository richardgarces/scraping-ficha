from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_lodoro_target = parse_shopify_target

LodoroStore = make_shopify_store(
    store_id="lodoro",
    title="Lodoro",
    site="www.lodoro.cl",
    base="https://www.lodoro.cl",
    category_help="Handle de colección Shopify, por ejemplo perfumes",
)
