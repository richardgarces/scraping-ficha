from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_dockers_target = parse_shopify_target

DockersStore = make_shopify_store(
    store_id="dockers",
    title="Dockers",
    site="www.dockers.cl",
    base="https://www.dockers.cl",
    category_help="Handle de colección Shopify",
)
