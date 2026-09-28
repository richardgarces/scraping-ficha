from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_etienne_target = parse_shopify_target

EtienneStore = make_shopify_store(
    store_id="etienne",
    title="Etienne",
    site="www.etienne.cl",
    base="https://www.etienne.cl",
    category_help="Handle de colección Shopify",
)
