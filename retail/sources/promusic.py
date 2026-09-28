from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_promusic_target = parse_shopify_target

PromusicStore = make_shopify_store(
    store_id="promusic",
    title="Pro Music",
    site="www.promusic.cl",
    base="https://www.promusic.cl",
    category_help="Handle de colección Shopify, por ejemplo guitarras",
)
