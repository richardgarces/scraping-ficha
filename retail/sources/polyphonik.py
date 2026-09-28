from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_polyphonik_target = parse_shopify_target

PolyphonikStore = make_shopify_store(
    store_id="polyphonik",
    title="Polyphonik",
    site="www.polyphonik.cl",
    base="https://www.polyphonik.cl",
    category_help="Handle de colección Shopify, por ejemplo vinilos",
)
