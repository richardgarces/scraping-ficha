from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_back_online_target = parse_shopify_target

BackOnlineStore = make_shopify_store(
    store_id="back_online",
    title="Back Online",
    site="www.backonline.cl",
    base="https://www.backonline.cl",
    category_help="Handle de colección Shopify",
)
