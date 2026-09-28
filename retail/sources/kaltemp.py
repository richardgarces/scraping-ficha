from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_kaltemp_target = parse_shopify_target

KaltempStore = make_shopify_store(
    store_id="kaltemp",
    title="Kaltemp",
    site="www.kaltemp.cl",
    base="https://www.kaltemp.cl",
    category_help="Handle de colección Shopify, por ejemplo aires",
)
