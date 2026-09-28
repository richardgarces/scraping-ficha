from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_kidsclub_target = parse_shopify_target

KidsclubStore = make_shopify_store(
    store_id="kidsclub",
    title="Kids Club",
    site="www.kidsclub.cl",
    base="https://www.kidsclub.cl",
    category_help="Handle de colección Shopify, por ejemplo infantil",
)
