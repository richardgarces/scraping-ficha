from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_bamers_target = parse_shopify_target

BamersStore = make_shopify_store(
    store_id="bamers",
    title="Bamers",
    site="www.bamers.cl",
    base="https://www.bamers.cl",
    category_help="Handle de colección Shopify",
)
