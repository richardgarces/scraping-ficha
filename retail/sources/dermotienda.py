from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_dermotienda_target = parse_shopify_target

DermotiendaStore = make_shopify_store(
    store_id="dermotienda",
    title="Dermotienda",
    site="www.dermotienda.cl",
    base="https://www.dermotienda.cl",
    category_help="Handle de colección Shopify, por ejemplo cremas",
)
