from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_mates_target = parse_shopify_target

MatesStore = make_shopify_store(
    store_id="mates",
    title="Mates.cl",
    site="mates.cl",
    base="https://mates.cl",
    category_help="Handle de colección Shopify, por ejemplo mates",
)
