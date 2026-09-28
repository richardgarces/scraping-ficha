from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_hitway_target = parse_shopify_target

HitwayStore = make_shopify_store(
    store_id="hitway",
    title="Hitway",
    site="www.hitway.cl",
    base="https://www.hitway.cl",
    category_help="Handle de colección Shopify, por ejemplo vinilos",
)
