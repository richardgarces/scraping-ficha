from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_vincenzi_target = parse_shopify_target

VincenziStore = make_shopify_store(
    store_id="vincenzi",
    title="Vincenzi",
    site="www.vincenzi.cl",
    base="https://www.vincenzi.cl",
    category_help="Handle de colección Shopify, por ejemplo toldos",
)
