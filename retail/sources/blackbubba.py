from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_blackbubba_target = parse_shopify_target

BlackbubbaStore = make_shopify_store(
    store_id="blackbubba",
    title="Black Bubba",
    site="www.blackbubba.com",
    base="https://www.blackbubba.com",
    category_help="Handle de colección Shopify, por ejemplo mochilas",
)
