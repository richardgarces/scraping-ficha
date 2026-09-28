from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_dib_target = parse_shopify_target

DibStore = make_shopify_store(
    store_id="dib",
    title="DIB Alfombras",
    site="www.dib.cl",
    base="https://www.dib.cl",
    category_help="Handle de colección Shopify, por ejemplo alfombras",
)
