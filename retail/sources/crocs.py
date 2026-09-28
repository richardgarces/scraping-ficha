from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_crocs_target = parse_shopify_target

CrocsStore = make_shopify_store(
    store_id="crocs",
    title="Crocs",
    site="www.crocs.cl",
    base="https://www.crocs.cl",
    category_help="Handle de colección Shopify",
)
