from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_imahe_target = parse_shopify_target

ImaheStore = make_shopify_store(
    store_id="imahe",
    title="Imahe",
    site="www.imahe.cl",
    base="https://www.imahe.cl",
    category_help="Handle de colección Shopify, por ejemplo gastronomia profesional",
)
