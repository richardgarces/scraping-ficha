from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_merrell_target = parse_shopify_target

MerrellStore = make_shopify_store(
    store_id="merrell",
    title="Merrell",
    site="www.merrell.cl",
    base="https://www.merrell.cl",
    category_help="Handle de colección Shopify",
)
