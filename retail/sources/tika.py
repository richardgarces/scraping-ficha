from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_tika_target = parse_shopify_target

TikaStore = make_shopify_store(
    store_id="tika",
    title="Tika Foods",
    site="tikafoods.com",
    base="https://tikafoods.com",
    category_help="Handle de colección Shopify, por ejemplo ofertas-tika",
)
