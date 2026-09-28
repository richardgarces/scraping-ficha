from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_ironside_target = parse_shopify_target

IronsideStore = make_shopify_store(
    store_id="ironside",
    title="Ironside",
    site="www.ironside.cl",
    base="https://www.ironside.cl",
    category_help="Handle de colección Shopify, por ejemplo fitness",
)
