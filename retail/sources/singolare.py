from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_singolare_target = parse_shopify_target

SingolareStore = make_shopify_store(
    store_id="singolare",
    title="Singolare",
    site="www.singolare.cl",
    base="https://www.singolare.cl",
    category_help="Handle de colección Shopify, por ejemplo poleras",
)
