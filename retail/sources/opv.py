from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_opv_target = parse_shopify_target

OpvStore = make_shopify_store(
    store_id="opv",
    title="OPV",
    site="www.opv.cl",
    base="https://www.opv.cl",
    category_help="Handle de colección Shopify",
)
