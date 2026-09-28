from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_medular_target = parse_shopify_target

MedularStore = make_shopify_store(
    store_id="medular",
    title="Medular",
    site="www.medular.cl",
    base="https://www.medular.cl",
    category_help="Handle de colección Shopify",
)
