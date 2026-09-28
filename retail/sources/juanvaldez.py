from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_juanvaldez_target = parse_shopify_target

JuanvaldezStore = make_shopify_store(
    store_id="juanvaldez",
    title="Juan Valdez",
    site="www.juanvaldez.cl",
    base="https://www.juanvaldez.cl",
    category_help="Handle de colección Shopify, por ejemplo cafe",
)
