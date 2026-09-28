from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_himalaya_target = parse_shopify_target

HimalayaStore = make_shopify_store(
    store_id="himalaya",
    title="Rincón Himalaya",
    site="www.rinconhimalaya.cl",
    base="https://www.rinconhimalaya.cl",
    category_help="Handle de colección Shopify, por ejemplo decoracion",
)
