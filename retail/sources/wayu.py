from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_wayu_target = parse_shopify_target

WayuStore = make_shopify_store(
    store_id="wayu",
    title="Wayu",
    site="www.wayu.cl",
    base="https://www.wayu.cl",
    category_help="Handle de colección Shopify, por ejemplo parrilla",
)
