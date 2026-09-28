from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_dpgoutlet_target = parse_shopify_target

DpgoutletStore = make_shopify_store(
    store_id="dpgoutlet",
    title="DPG Outlet",
    site="www.dpgoutlet.cl",
    base="https://www.dpgoutlet.cl",
    category_help="Handle de colección Shopify, por ejemplo perfumes",
)
