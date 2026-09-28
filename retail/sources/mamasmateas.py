from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_mamasmateas_target = parse_shopify_target

MamasmateasStore = make_shopify_store(
    store_id="mamasmateas",
    title="mamás mateas",
    site="www.mamasmateas.cl",
    base="https://www.mamasmateas.cl",
    category_help="Handle de colección Shopify, por ejemplo cochecitos",
)
