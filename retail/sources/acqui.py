from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_acqui_target = parse_shopify_target

AcquiStore = make_shopify_store(
    store_id="acqui",
    title="Acqui",
    site="www.acqui.cl",
    base="https://www.acqui.cl",
    category_help="Handle de colección Shopify, por ejemplo camillas",
)
