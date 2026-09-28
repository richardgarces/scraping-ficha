from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_sharkninja_target = parse_shopify_target

SharkninjaStore = make_shopify_store(
    store_id="sharkninja",
    title="Shark Ninja",
    site="www.sharkninja.cl",
    base="https://www.sharkninja.cl",
    category_help="Handle de colección Shopify, por ejemplo aspiradoras",
)
