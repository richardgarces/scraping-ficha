from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_relan_target = parse_shopify_target

RelanStore = make_shopify_store(
    store_id="relan",
    title="Relan",
    site="www.relan.cl",
    base="https://www.relan.cl",
    category_help="Handle de colección Shopify, por ejemplo sillones",
)
