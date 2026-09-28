from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_simplepuro_target = parse_shopify_target

SimplepuroStore = make_shopify_store(
    store_id="simplepuro",
    title="Simple by Puro",
    site="www.simplebypuro.cl",
    base="https://www.simplebypuro.cl",
    category_help="Handle de colección Shopify",
)
