from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_misjoyas_target = parse_shopify_target

MisjoyasStore = make_shopify_store(
    store_id="misjoyas",
    title="MisJoyas",
    site="misjoyas.cl",
    base="https://misjoyas.cl",
    category_help="Handle de colección Shopify, por ejemplo anillos",
)
