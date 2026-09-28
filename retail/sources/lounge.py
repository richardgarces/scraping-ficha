from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_lounge_target = parse_shopify_target

LoungeStore = make_shopify_store(
    store_id="lounge",
    title="Lounge",
    site="www.lounge.cl",
    base="https://www.lounge.cl",
    category_help="Handle de colección Shopify",
)
