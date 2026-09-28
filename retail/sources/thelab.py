from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_thelab_target = parse_shopify_target

ThelabStore = make_shopify_store(
    store_id="thelab",
    title="The Lab",
    site="www.thelabstore.cl",
    base="https://www.thelabstore.cl",
    category_help="Handle de colección Shopify, por ejemplo lentes",
)
