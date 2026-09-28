from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_toyng_target = parse_shopify_target

ToyngStore = make_shopify_store(
    store_id="toyng",
    title="Toyng",
    site="www.toyng.cl",
    base="https://www.toyng.cl",
    category_help="Handle de colección Shopify",
)
