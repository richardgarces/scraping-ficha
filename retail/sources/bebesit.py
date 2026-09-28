from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_bebesit_target = parse_shopify_target

BebesitStore = make_shopify_store(
    store_id="bebesit",
    title="Bebesit",
    site="www.bebesit.cl",
    base="https://www.bebesit.cl",
    category_help="Handle de colección Shopify",
)
