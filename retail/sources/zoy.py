from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_zoy_target = parse_shopify_target

ZoyStore = make_shopify_store(
    store_id="zoy",
    title="Zoy Home",
    site="www.zoyhome.cl",
    base="https://www.zoyhome.cl",
    category_help="Handle de colección Shopify, por ejemplo sillones",
)
