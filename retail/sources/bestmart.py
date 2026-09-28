from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_bestmart_target = parse_shopify_target

BestmartStore = make_shopify_store(
    store_id="bestmart",
    title="Bestmart",
    site="www.bestmart.cl",
    base="https://www.bestmart.cl",
    category_help="Handle de colección Shopify, por ejemplo tecnologia",
)
