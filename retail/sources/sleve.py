from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_sleve_target = parse_shopify_target

SleveStore = make_shopify_store(
    store_id="sleve",
    title="Sleve",
    site="www.sleve.cl",
    base="https://www.sleve.cl",
    category_help="Handle de colección Shopify, por ejemplo audio",
)
