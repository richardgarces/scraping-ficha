from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_nacional_target = parse_shopify_target

NacionalStore = make_shopify_store(
    store_id="nacional",
    title="Librería Nacional",
    site="nacional.cl",
    base="https://nacional.cl",
    category_help="Handle de colección Shopify",
)
