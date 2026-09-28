from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_japijane_target = parse_shopify_target

JapijaneStore = make_shopify_store(
    store_id="japijane",
    title="Japi Jane",
    site="www.japijane.cl",
    base="https://www.japijane.cl",
    category_help="Handle de colección Shopify, por ejemplo fragancias",
)
