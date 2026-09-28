from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_homemobili_target = parse_shopify_target

HomemobiliStore = make_shopify_store(
    store_id="homemobili",
    title="Home Mobili",
    site="homemobili.cl",
    base="https://homemobili.cl",
    category_help="Handle de colección Shopify, por ejemplo comedor",
)
