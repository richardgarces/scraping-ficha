from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_doite_target = parse_shopify_target

DoiteStore = make_shopify_store(
    store_id="doite",
    title="Doite",
    site="www.doite.cl",
    base="https://www.doite.cl",
    category_help="Handle de colección Shopify, por ejemplo camping",
)
