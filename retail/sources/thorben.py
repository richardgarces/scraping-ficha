from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_thorben_target = parse_shopify_target

ThorbenStore = make_shopify_store(
    store_id="thorben",
    title="Thörben",
    site="thorbenstore.cl",
    base="https://thorbenstore.cl",
    category_help="Handle de colección Shopify, por ejemplo hogar",
)
