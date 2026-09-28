from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_bfresh_target = parse_shopify_target

BfreshStore = make_shopify_store(
    store_id="bfresh",
    title="bfresh",
    site="www.bfresh.cl",
    base="https://www.bfresh.cl",
    category_help="Handle de colección Shopify, por ejemplo limpieza",
)
