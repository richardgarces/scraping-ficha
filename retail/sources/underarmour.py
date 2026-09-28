from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_underarmour_target = parse_shopify_target

UnderarmourStore = make_shopify_store(
    store_id="underarmour",
    title="Under Armour",
    site="www.underarmour.cl",
    base="https://www.underarmour.cl",
    category_help="Handle de colección Shopify",
)
