from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_outletdelcafe_target = parse_shopify_target

OutletdelcafeStore = make_shopify_store(
    store_id="outletdelcafe",
    title="Outlet del Café",
    site="www.outletdelcafe.cl",
    base="https://www.outletdelcafe.cl",
    category_help="Handle de colección Shopify, por ejemplo cafe",
)
