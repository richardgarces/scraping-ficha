from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_mashini_target = parse_shopify_target

MashiniStore = make_shopify_store(
    store_id="mashini",
    title="Mashini",
    site="www.mashini.cl",
    base="https://www.mashini.cl",
    category_help="Handle de colección Shopify",
)
