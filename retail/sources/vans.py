from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_vans_target = parse_shopify_target

VansStore = make_shopify_store(
    store_id="vans",
    title="Vans",
    site="www.vans.cl",
    base="https://www.vans.cl",
    category_help="Handle de colección Shopify",
)
