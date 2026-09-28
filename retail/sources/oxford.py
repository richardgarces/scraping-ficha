from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_oxford_target = parse_shopify_target

OxfordStore = make_shopify_store(
    store_id="oxford",
    title="Oxford Store",
    site="www.oxfordstore.cl",
    base="https://www.oxfordstore.cl",
    category_help="Handle de colección Shopify",
)
