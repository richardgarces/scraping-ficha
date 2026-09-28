from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_teh_target = parse_shopify_target

TehStore = make_shopify_store(
    store_id="teh",
    title="TEH",
    site="www.teh.cl",
    base="https://www.teh.cl",
    category_help="Handle de colección Shopify, por ejemplo herramientas",
)
