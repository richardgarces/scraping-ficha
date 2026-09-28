from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_bazhars_target = parse_shopify_target

BazharsStore = make_shopify_store(
    store_id="bazhars",
    title="Bazhars",
    site="www.bazhars.cl",
    base="https://www.bazhars.cl",
    category_help="Handle de colección Shopify, por ejemplo alfombras",
)
