from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_nutriscomarket_cl_target = parse_shopify_target

NutriscomarketClStore = make_shopify_store(
    store_id="nutriscomarket_cl",
    title="Nutriscomarket.cl",
    site="www.nutriscomarket.cl",
    base="https://www.nutriscomarket.cl",
    category_help="Handle de colección Shopify",
)
