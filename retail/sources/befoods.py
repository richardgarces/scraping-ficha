from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_befoods_target = parse_shopify_target

BefoodsStore = make_shopify_store(
    store_id="befoods",
    title="be foods",
    site="www.befoods.cl",
    base="https://www.befoods.cl",
    category_help="Handle de colección Shopify, por ejemplo mascotas",
)
