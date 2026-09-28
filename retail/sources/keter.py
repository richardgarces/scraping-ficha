from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_keter_target = parse_shopify_target

KeterStore = make_shopify_store(
    store_id="keter",
    title="Keter",
    site="www.keter.cl",
    base="https://www.keter.cl",
    category_help="Handle de colección Shopify, por ejemplo almacenaje",
)
