from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_amphora_target = parse_shopify_target

AmphoraStore = make_shopify_store(
    store_id="amphora",
    title="Amphora",
    site="www.amphora.cl",
    base="https://www.amphora.cl",
    category_help="Handle de colección Shopify, por ejemplo carteras",
)
