from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_yauras_target = parse_shopify_target

YaurasStore = make_shopify_store(
    store_id="yauras",
    title="Yauras",
    site="yauras.cl",
    base="https://yauras.cl",
    category_help="Handle de colección Shopify, por ejemplo perfumes",
)
