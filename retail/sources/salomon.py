from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_salomon_target = parse_shopify_target

SalomonStore = make_shopify_store(
    store_id="salomon",
    title="Salomon",
    site="www.salomon.cl",
    base="https://www.salomon.cl",
    category_help="Handle de colección Shopify",
)
