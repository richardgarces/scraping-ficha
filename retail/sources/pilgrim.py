from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_pilgrim_target = parse_shopify_target

PilgrimStore = make_shopify_store(
    store_id="pilgrim",
    title="Pilgrim",
    site="www.pilgrim.cl",
    base="https://www.pilgrim.cl",
    category_help="Handle de colección Shopify, por ejemplo maletas",
)
