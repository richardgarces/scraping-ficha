from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_scaldasonno_target = parse_shopify_target

ScaldasonnoStore = make_shopify_store(
    store_id="scaldasonno",
    title="Scaldasonno",
    site="scaldasonno.cl",
    base="https://scaldasonno.cl",
    category_help="Handle de colección Shopify, por ejemplo calientacamas",
)
